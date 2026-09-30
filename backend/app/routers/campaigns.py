"""Core domain CRUD: ICP profiles, campaigns, prospects, and the approval inbox.

Kept as one router file since these all share the same handful of tables and the
same request flow (create a prospect -> graph runs to the approval interrupt ->
review -> approve/reject) rather than being independent concerns.
"""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import db
from app.discovery import discover_candidates
from app.graph import get_checkpointer, get_graph, sync_after_run
from app.models import (
    ApprovalDecision,
    CampaignCreate,
    CampaignOut,
    EmailOut,
    ICPProfileCreate,
    ICPProfileOut,
    ProspectCreate,
    ProspectOut,
)

DISCOVERY_COUNT = 8  # candidates requested per "Find prospects" click -- no picker in the UI yet

logger = logging.getLogger(__name__)
router = APIRouter()


# ------------------------------------------------------------------------ ICP profiles

@router.post("/icp-profiles", response_model=ICPProfileOut)
def create_icp_profile(body: ICPProfileCreate):
    row = db.fetch_one(
        "insert into icp_profiles (name, criteria) values (%s, %s) returning *",
        (body.name, body.criteria),
    )
    return row


@router.get("/icp-profiles", response_model=list[ICPProfileOut])
def list_icp_profiles():
    return db.fetch_all("select * from icp_profiles order by created_at desc")


@router.delete("/icp-profiles/{icp_profile_id}", status_code=204)
def delete_icp_profile(icp_profile_id: str):
    if not db.fetch_one("select id from icp_profiles where id = %s", (icp_profile_id,)):
        raise HTTPException(status_code=404, detail="ICP profile not found")
    # campaigns.icp_profile_id is ON DELETE SET NULL, so existing campaigns just fall back
    # to scoring new prospects as a generic B2B fit rather than being blocked or cascaded.
    db.execute("delete from icp_profiles where id = %s", (icp_profile_id,))


# --------------------------------------------------------------------------- campaigns

@router.post("/campaigns", response_model=CampaignOut)
def create_campaign(body: CampaignCreate):
    row = db.fetch_one(
        """
        insert into campaigns (name, icp_profile_id, sender_persona, followup_count, followup_delay_hours)
        values (%s, %s, %s, %s, %s) returning *
        """,
        (body.name, body.icp_profile_id, body.sender_persona, body.followup_count, body.followup_delay_hours),
    )
    return row


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns():
    return db.fetch_all("select * from campaigns order by created_at desc")


def _get_campaign(campaign_id: str) -> dict:
    campaign = db.fetch_one("select * from campaigns where id = %s", (campaign_id,))
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def _get_icp_criteria(campaign: dict) -> str | None:
    if not campaign["icp_profile_id"]:
        return None
    icp = db.fetch_one("select criteria from icp_profiles where id = %s", (campaign["icp_profile_id"],))
    return icp["criteria"] if icp else None


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: str):
    return _get_campaign(campaign_id)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: str):
    _get_campaign(campaign_id)
    prospects = db.fetch_all("select thread_id from prospects where campaign_id = %s", (campaign_id,))
    checkpointer = get_checkpointer()
    for prospect in prospects:
        checkpointer.delete_thread(prospect["thread_id"])
    # prospects/emails/email_events all cascade via ON DELETE CASCADE.
    db.execute("delete from campaigns where id = %s", (campaign_id,))


# --------------------------------------------------------------------------- prospects

def _invoke_and_sync(graph_input, thread_id: str, prospect_id: str, step: int) -> None:
    """Runs in a FastAPI background task: invokes the graph up to its next pause/end,
    then persists the result. Kept as a plain function (no queue) since a single LLM
    pipeline run takes a few seconds -- a background task is enough to not block the
    HTTP response, and we don't need retries/distribution at this scale.

    A failure here (e.g. a transient LLM/search API error) would otherwise leave the
    prospect stuck at its in-progress status forever with no visible cause -- catching
    it and marking the prospect 'error' keeps that failure visible instead of silent."""
    graph = get_graph()
    try:
        graph.invoke(graph_input, config={"configurable": {"thread_id": thread_id}})
        sync_after_run(prospect_id, thread_id, step)
    except Exception:
        logger.exception("Pipeline run failed for prospect %s (thread %s)", prospect_id, thread_id)
        db.execute(
            "update prospects set status = 'error', updated_at = now() where id = %s", (prospect_id,)
        )


def _enter_pipeline(
    prospect_id: str,
    thread_id: str,
    campaign: dict,
    icp_criteria: str | None,
    body: ProspectCreate,
    background_tasks: BackgroundTasks,
) -> None:
    """Kicks off the research -> score -> draft -> critic -> approval graph run for a
    prospect that already has a DB row (freshly inserted, or a discovered candidate
    being promoted via start_outreach). The one shared entry point into the pipeline,
    so manual and AI-discovered prospects run through identical, unmodified logic."""
    initial_state = {
        "prospect_id": prospect_id,
        "name": body.name,
        "title": body.title,
        "company": body.company,
        "context": body.context,
        "icp_criteria": icp_criteria,
        "sender_persona": campaign["sender_persona"],
        "stage": "new",
        "step": 0,
    }
    background_tasks.add_task(_invoke_and_sync, initial_state, thread_id, prospect_id, 0)


@router.post("/campaigns/{campaign_id}/prospects", response_model=ProspectOut)
def create_prospect(
    campaign_id: str,
    body: ProspectCreate,
    background_tasks: BackgroundTasks,
):
    campaign = _get_campaign(campaign_id)
    icp_criteria = _get_icp_criteria(campaign)

    thread_id = str(uuid.uuid4())
    prospect = db.fetch_one(
        """
        insert into prospects (campaign_id, name, title, company, email, context, status, thread_id)
        values (%s, %s, %s, %s, %s, %s, 'researching', %s) returning *
        """,
        (campaign_id, body.name, body.title, body.company, body.email, body.context, thread_id),
    )
    _enter_pipeline(prospect["id"], thread_id, campaign, icp_criteria, body, background_tasks)
    return prospect


# --------------------------------------------------------------------------- discovery

def _run_discovery(campaign_id: str, icp_criteria: str | None) -> None:
    """Runs in a FastAPI background task, same pattern as _invoke_and_sync: a Tavily +
    Gemini call takes real time, so this can't block the POST /discover response."""
    try:
        candidates = discover_candidates(icp_criteria or "General B2B software buyer.", DISCOVERY_COUNT)
    except Exception:
        logger.exception("Prospect discovery failed for campaign %s", campaign_id)
        db.execute("update campaigns set discovery_status = 'error' where id = %s", (campaign_id,))
        return

    if not candidates:
        db.execute("update campaigns set discovery_status = 'no_candidates_found' where id = %s", (campaign_id,))
        return

    for candidate in candidates:
        db.execute(
            """
            insert into prospects (campaign_id, name, title, company, email, context, status, thread_id)
            values (%s, %s, %s, %s, null, %s, 'discovered', %s)
            """,
            (
                campaign_id,
                candidate["name"],
                candidate.get("title"),
                candidate["company"],
                candidate.get("context"),
                str(uuid.uuid4()),
            ),
        )
    db.execute("update campaigns set discovery_status = 'done' where id = %s", (campaign_id,))


@router.post("/campaigns/{campaign_id}/discover", response_model=CampaignOut)
def discover_prospects(campaign_id: str, background_tasks: BackgroundTasks):
    campaign = _get_campaign(campaign_id)
    icp_criteria = _get_icp_criteria(campaign)
    db.execute("update campaigns set discovery_status = 'running' where id = %s", (campaign_id,))
    background_tasks.add_task(_run_discovery, campaign_id, icp_criteria)
    return db.fetch_one("select * from campaigns where id = %s", (campaign_id,))


@router.post("/prospects/{prospect_id}/start-outreach", response_model=ProspectOut)
def start_outreach(prospect_id: str, body: ProspectCreate, background_tasks: BackgroundTasks):
    """Confirms/edits an AI-discovered candidate's details (an email in particular --
    discovery never guesses one) and promotes it into the real pipeline, via the exact
    same _enter_pipeline() call manual prospect creation uses."""
    prospect = _get_prospect(prospect_id)
    if prospect["status"] != "discovered":
        raise HTTPException(status_code=409, detail=f"Prospect is not a pending discovery candidate (status={prospect['status']})")

    campaign = _get_campaign(prospect["campaign_id"])
    icp_criteria = _get_icp_criteria(campaign)

    thread_id = str(uuid.uuid4())
    updated = db.fetch_one(
        """
        update prospects set name = %s, title = %s, company = %s, email = %s, context = %s,
            status = 'researching', thread_id = %s, updated_at = now()
        where id = %s returning *
        """,
        (body.name, body.title, body.company, body.email, body.context, thread_id, prospect_id),
    )
    _enter_pipeline(prospect_id, thread_id, campaign, icp_criteria, body, background_tasks)
    return updated


@router.get("/campaigns/{campaign_id}/prospects", response_model=list[ProspectOut])
def list_prospects(campaign_id: str):
    _get_campaign(campaign_id)
    return db.fetch_all(
        "select * from prospects where campaign_id = %s order by created_at desc", (campaign_id,)
    )


def _get_prospect(prospect_id: str) -> dict:
    prospect = db.fetch_one("select * from prospects where id = %s", (prospect_id,))
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect not found")
    return prospect


@router.get("/prospects/{prospect_id}", response_model=ProspectOut)
def get_prospect(prospect_id: str):
    return _get_prospect(prospect_id)


@router.delete("/prospects/{prospect_id}", status_code=204)
def delete_prospect(prospect_id: str):
    prospect = _get_prospect(prospect_id)
    get_checkpointer().delete_thread(prospect["thread_id"])
    db.execute("delete from prospects where id = %s", (prospect_id,))  # emails/email_events cascade


@router.get("/prospects/{prospect_id}/emails", response_model=list[EmailOut])
def list_prospect_emails(prospect_id: str):
    _get_prospect(prospect_id)
    return db.fetch_all(
        "select * from emails where prospect_id = %s order by step asc", (prospect_id,)
    )


# --------------------------------------------------------------------------- approvals

@router.get("/approvals", response_model=list[ProspectOut])
def list_pending_approvals():
    return db.fetch_all(
        "select * from prospects where status = 'pending_approval' order by updated_at asc"
    )


@router.post("/prospects/{prospect_id}/approval", response_model=ProspectOut)
def submit_approval(
    prospect_id: str,
    decision: ApprovalDecision,
    background_tasks: BackgroundTasks,
):
    prospect = _get_prospect(prospect_id)
    if prospect["status"] != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Prospect is not awaiting approval (status={prospect['status']})")

    step = prospect["followups_sent"]
    email_row = db.fetch_one(
        "select * from emails where prospect_id = %s and step = %s", (prospect_id, step)
    )
    if not email_row:
        raise HTTPException(status_code=409, detail="No draft found for this prospect")

    if decision.action == "approve":
        resume_payload = {
            "action": "approve",
            "edited_subject": decision.edited_subject,
            "edited_body": decision.edited_body,
            "email_id": email_row["id"],
        }
        db.execute("update prospects set status = 'sending', updated_at = now() where id = %s", (prospect_id,))
    elif decision.action == "reject":
        resume_payload = {"action": "reject", "rejection_reason": decision.rejection_reason}
    else:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    from langgraph.types import Command

    background_tasks.add_task(
        _invoke_and_sync, Command(resume=resume_payload), prospect["thread_id"], prospect_id, step
    )
    return {**prospect, "status": "sending" if decision.action == "approve" else "pending_approval"}


# --------------------------------------------------------------------------- analytics

@router.get("/campaigns/{campaign_id}/analytics")
def campaign_analytics(campaign_id: str) -> dict:
    _get_campaign(campaign_id)

    funnel = db.fetch_all(
        "select status, count(*) as count from prospects where campaign_id = %s group by status",
        (campaign_id,),
    )
    sent_emails = db.fetch_all(
        "select e.id from emails e join prospects p on p.id = e.prospect_id"
        " where p.campaign_id = %s and e.status = 'sent'",
        (campaign_id,),
    )
    sent_ids = [row["id"] for row in sent_emails]
    opened = clicked = 0
    if sent_ids:
        events = db.fetch_all(
            "select event_type, count(distinct email_id) as count from email_events"
            " where email_id = any(%s) group by event_type",
            (sent_ids,),
        )
        for row in events:
            if row["event_type"] == "opened":
                opened = row["count"]
            elif row["event_type"] == "clicked":
                clicked = row["count"]

    total_sent = len(sent_ids)
    return {
        "funnel": {row["status"]: row["count"] for row in funnel},
        "emails_sent": total_sent,
        "open_rate": round(opened / total_sent, 3) if total_sent else 0,
        "click_rate": round(clicked / total_sent, 3) if total_sent else 0,
    }
