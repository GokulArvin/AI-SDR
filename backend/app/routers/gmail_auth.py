"""Connect-your-Gmail flow. The actual send/poll logic lives in app/gmail.py; this
router is just the three HTTP endpoints around it."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from googleapiclient.errors import HttpError

from app import db, gmail
from app.config import get_settings

router = APIRouter(prefix="/gmail")


@router.get("/connect")
def connect() -> dict:
    """Frontend calls this to get the Google consent URL, then redirects the
    browser there itself."""
    return {"authorization_url": gmail.get_authorization_url()}


@router.get("/callback")
def callback(code: str, state: str):
    # Google redirects the browser straight here (never through the frontend), so
    # every failure path below must end in a redirect back into the app rather than
    # raising -- an HTTPException here would show the user a raw, unstyled JSON error
    # page instead of a clear explanation on the Settings page.
    frontend_url = get_settings().frontend_url
    try:
        email_address = gmail.handle_oauth_callback(code, state)
    except gmail.GmailScopeError:
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error=insufficient_scope")
    except ValueError:
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error=invalid_state")
    except HttpError:
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error=google_api_error")
    except Exception:
        return RedirectResponse(url=f"{frontend_url}/settings?gmail_error=unknown")

    return RedirectResponse(url=f"{frontend_url}/settings?gmail_connected={email_address}")


@router.get("/status")
def status() -> dict:
    row = db.fetch_one("select email_address, created_at from gmail_connections limit 1")
    return {"connected": bool(row), "email_address": row["email_address"] if row else None}
