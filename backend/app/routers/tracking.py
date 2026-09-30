"""Public endpoints an email client hits when it renders the tracking pixel or a
recipient clicks a link -- intentionally unauthenticated, they're not called by our
own frontend. See app/tracking.py for how these URLs get embedded on send."""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse, Response

from app.tracking import log_event

router = APIRouter(prefix="/track")

# Smallest valid transparent GIF, served for every open-tracking hit.
_PIXEL = bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b")


@router.get("/open/{email_id}.png")
def track_open(email_id: str):
    log_event(email_id, "opened")
    return Response(content=_PIXEL, media_type="image/gif")


@router.get("/click/{email_id}")
def track_click(email_id: str, url: str):
    log_event(email_id, "clicked", {"url": url})
    return RedirectResponse(url=url)
