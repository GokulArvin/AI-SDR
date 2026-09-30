"""Gmail integration: OAuth2 connect flow, sending, and reply detection.

We deliberately send through the user's own connected Gmail account rather than a
third-party ESP (Mailjet/SendGrid/etc). Two reasons: (1) real rep-facing outreach
tools (Yesware, Mixmax, Salesloft) work this way -- they plug into the rep's mailbox
rather than requiring a dedicated sending domain -- which is the more realistic
pattern for an individual-outreach tool; (2) it needs no domain ownership or DNS
records, which a transactional-ESP setup (domain auth, inbound-parse MX records)
would require and this project doesn't have. The trade-off is Gmail's send-volume
limits, which is a non-issue at portfolio-project scale.

Single-tenant app: at most one Gmail mailbox is ever connected, so `gmail_connections`
never holds more than one row.

Reply detection: rather than an inbound-parse webhook (which needs an owned domain),
we poll each active thread's message list via the Gmail API from cron.py and check
whether any message in it isn't labeled SENT (i.e. came back from the prospect).
"""

import base64
import os
from email.mime.text import MIMEText

import googleapiclient.discovery
from cryptography.fernet import Fernet
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app import db
from app.config import get_settings
from app.tracking import embed_tracking

# oauthlib treats the granted scope list not matching the requested one *exactly*
# (different order, or Google silently adding "openid") as a hard error by default --
# a well-known false positive against Google's OAuth endpoint specifically, not an
# actual security problem, so relax it. Must be set before flow.fetch_token() runs.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


# ------------------------------------------------------------------ token encryption

def _fernet() -> Fernet:
    return Fernet(get_settings().token_encryption_key.encode())


def _encrypt(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def _decrypt(token_enc: str) -> str:
    return _fernet().decrypt(token_enc.encode()).decode()


# ------------------------------------------------------------- OAuth "state" nonce
# The Google callback carries no auth of ours. Checking the callback's state against
# what we handed out is enough to stop a third-party site from tricking a browser
# into completing the OAuth flow with an attacker-controlled authorization code
# (CSRF on the callback) -- there's no per-user identity to bind it to here.
#
# We also stash the PKCE code_verifier here, keyed by the same state: the Flow
# object that builds the authorization URL generates a random verifier internally,
# but the callback needs a *different* Flow instance (a fresh request) to exchange
# the code -- without persisting the verifier ourselves, Google's token endpoint
# rejects the exchange with "Missing code verifier".

_pending_states: dict[str, str] = {}  # state -> code_verifier


class GmailScopeError(Exception):
    """Raised when the user's Google OAuth grant is missing gmail.send/gmail.readonly --
    e.g. they didn't check every permission box on Google's consent screen."""


# --------------------------------------------------------------------------- OAuth flow

def _flow() -> Flow:
    settings = get_settings()
    client_config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=settings.google_redirect_uri)


def get_authorization_url() -> str:
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",  # force a refresh_token even if the user connected before
    )
    _pending_states[state] = flow.code_verifier
    return url


def handle_oauth_callback(code: str, state: str) -> str:
    """Exchanges the auth code, stores the connection, returns the connected email."""
    code_verifier = _pending_states.get(state)
    if code_verifier is None:
        raise ValueError("Invalid or expired OAuth state")

    flow = _flow()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials

    # Only consumed once the exchange actually succeeds -- if it fails (rate limit,
    # transient network error), the state stays valid so retrying the same callback
    # doesn't fail a second time with a misleading "state expired" instead of the
    # real error.
    _pending_states.pop(state, None)

    # Google can silently grant fewer scopes than requested (easy to miss a checkbox
    # on its consent screen for sensitive scopes on an unverified/"Testing" app) --
    # check what was actually granted before calling a Gmail API that would otherwise
    # fail downstream with an opaque 403 "insufficientPermissions".
    required_gmail_scopes = {
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.readonly",
    }
    granted_scopes = set(creds.scopes or [])
    if creds.scopes is not None and not required_gmail_scopes.issubset(granted_scopes):
        raise GmailScopeError("Gmail didn't grant all requested permissions.")

    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    email_address = service.users().getProfile(userId="me").execute()["emailAddress"]

    db.execute("delete from gmail_connections")
    db.execute(
        """
        insert into gmail_connections (email_address, refresh_token_enc, access_token, token_expiry)
        values (%(email)s, %(refresh_enc)s, %(access)s, %(expiry)s)
        """,
        {
            "email": email_address,
            "refresh_enc": _encrypt(creds.refresh_token),
            "access": creds.token,
            "expiry": creds.expiry,
        },
    )
    return email_address


def _load_credentials() -> Credentials:
    row = db.fetch_one(
        "select refresh_token_enc, access_token, token_expiry from gmail_connections limit 1"
    )
    if not row:
        raise RuntimeError("No Gmail account connected")

    settings = get_settings()
    creds = Credentials(
        token=row["access_token"],
        refresh_token=_decrypt(row["refresh_token_enc"]),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=SCOPES,
    )
    if not creds.valid:
        creds.refresh(GoogleRequest())
        db.execute(
            "update gmail_connections set access_token = %s, token_expiry = %s",
            (creds.token, creds.expiry),
        )
    return creds


# ------------------------------------------------------------------------------- send

def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    email_id: str,
    gmail_thread_id: str | None = None,
) -> dict:
    creds = _load_credentials()
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)

    html_body = embed_tracking(body.replace("\n", "<br/>"), email_id)
    message = MIMEText(html_body, "html")
    message["to"] = to_email
    message["subject"] = subject

    payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
    if gmail_thread_id:
        payload["threadId"] = gmail_thread_id

    sent = service.users().messages().send(userId="me", body=payload).execute()
    return {"message_id": sent["id"], "thread_id": sent["threadId"]}


# ------------------------------------------------------------------------ reply check

def has_reply(gmail_thread_id: str, our_message_id: str) -> bool:
    """True if the thread contains a message we didn't send (i.e. the prospect replied)."""
    creds = _load_credentials()
    service = googleapiclient.discovery.build("gmail", "v1", credentials=creds)
    thread = service.users().threads().get(userId="me", id=gmail_thread_id, format="minimal").execute()

    for message in thread.get("messages", []):
        if message["id"] == our_message_id:
            continue
        if "SENT" not in message.get("labelIds", []):
            return True
    return False
