"""The one scheduled entry point the whole system needs. An external scheduler (a
Render Cron Job or a scheduled GitHub Action, see README) hits this every ~15 minutes
with a shared secret. No task queue -- see graph.py's module docstring for why a
periodic "what's due" sweep is enough at this scale instead of Celery/Redis.

Two things happen on each tick:
1. Prospects waiting on a reply get their Gmail thread polled; a reply marks them
   done, no reply past the due time triggers the next follow-up (or completion).
2. That follow-up trigger re-invokes the *same* graph thread with stage="followup",
   which re-enters at the draft node and reuses the checkpointed research/score.

Processed synchronously in the request (not background tasks) -- tick volume is
small at this scale and a synchronous sweep is much easier to reason about and to
smoke-test with a plain curl call.
"""

from fastapi import APIRouter, Depends, Header, HTTPException

from app import db, gmail
from app.config import get_settings
from app.graph import get_graph, sync_after_run

router = APIRouter()


def require_cron_secret(x_cron_secret: str = Header(default="")) -> None:
    if x_cron_secret != get_settings().cron_secret:
        raise HTTPException(status_code=401, detail="Invalid cron secret")


@router.post("/cron/tick")
def run_tick(_: None = Depends(require_cron_secret)) -> dict:
    replied = 0
    followups_triggered = 0
    completed = 0
    errors: list[str] = []

    awaiting = db.fetch_all(
        "select p.*, c.followup_count from prospects p"
        " join campaigns c on c.id = p.campaign_id"
        " where p.status = 'awaiting_reply'"
    )

    for prospect in awaiting:
        try:
            step = prospect["followups_sent"] - 1  # the step of the email we most recently sent
            last_email = db.fetch_one(
                "select gmail_message_id, gmail_thread_id from emails"
                " where prospect_id = %s and step = %s and status = 'sent'",
                (prospect["id"], step),
            )
            if not last_email or not last_email["gmail_thread_id"]:
                continue

            if gmail.has_reply(last_email["gmail_thread_id"], last_email["gmail_message_id"]):
                db.execute(
                    "update prospects set status = 'replied', updated_at = now() where id = %s",
                    (prospect["id"],),
                )
                replied += 1
                continue

            if prospect["next_action_at"] is None or prospect["next_action_at"] > _now():
                continue  # not due yet

            # followups_sent counts every email sent so far, including the initial one,
            # so "follow-ups sent" = followups_sent - 1; stop once that reaches followup_count.
            if prospect["followups_sent"] - 1 >= prospect["followup_count"]:
                db.execute(
                    "update prospects set status = 'completed_no_response', updated_at = now() where id = %s",
                    (prospect["id"],),
                )
                completed += 1
                continue

            _trigger_followup(prospect)
            followups_triggered += 1
        except Exception as exc:  # noqa: BLE001 -- one bad prospect shouldn't stop the sweep
            errors.append(f"{prospect['id']}: {exc}")

    return {
        "checked": len(awaiting),
        "replied": replied,
        "followups_triggered": followups_triggered,
        "completed_no_response": completed,
        "errors": errors,
    }


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _trigger_followup(prospect: dict) -> None:
    step = prospect["followups_sent"]  # next follow-up number
    graph = get_graph()
    graph.invoke(
        {"stage": "followup", "step": step},
        config={"configurable": {"thread_id": prospect["thread_id"]}},
    )
    sync_after_run(prospect["id"], prospect["thread_id"], step)
