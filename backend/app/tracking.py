"""Self-hosted open/click tracking. We're not using an ESP dashboard (see gmail.py for
why), so outbound emails get their own 1x1 pixel and link-redirects pointing back at
this backend; app/routers/tracking.py serves those and logs the events."""

import re
from urllib.parse import quote

from app import db
from app.config import get_settings

_LINK_RE = re.compile(r'href="(https?://[^"]+)"')


def embed_tracking(html_body: str, email_id: str) -> str:
    base = get_settings().backend_public_url

    def _rewrite(match: re.Match) -> str:
        original_url = match.group(1)
        return f'href="{base}/track/click/{email_id}?url={quote(original_url, safe="")}"'

    body_with_tracked_links = _LINK_RE.sub(_rewrite, html_body)
    pixel = f'<img src="{base}/track/open/{email_id}.png" width="1" height="1" alt="" style="display:none" />'
    return f"{body_with_tracked_links}{pixel}"


def log_event(email_id: str, event_type: str, metadata: dict | None = None) -> None:
    db.execute(
        "insert into email_events (email_id, event_type, metadata) values (%s, %s, %s)",
        (email_id, event_type, db.Jsonb(metadata) if metadata else None),
    )
