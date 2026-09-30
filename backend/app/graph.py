"""The per-prospect agent pipeline: research -> ICP score -> draft -> critic -> human
approval -> send. One LangGraph graph, one Postgres-backed thread per prospect.

How the "wait days for a reply, then maybe follow up" part works: LangGraph's
`interrupt()` pauses a graph *mid-run* for a human decision and is resumed within the
same logical run -- it isn't meant to sleep for days. So multi-day waiting is modeled
one level up, in Postgres: after `send_node` runs, this graph invocation simply ends
(reaching END), and `prospects.next_action_at` records when it should be picked up
again. A cron tick (see cron.py) re-invokes the *same* thread_id later with
stage="followup", which re-enters at the draft node and reuses the state (research,
score, prior thread) already checkpointed for that prospect. LangGraph owns the
in-run reasoning and the human-approval pause; Postgres owns the long-horizon
scheduling. Two different kinds of "waiting", handled by the tool suited to each.
"""

import json
from typing import Literal, TypedDict

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from tavily import TavilyClient

from app import db
from app.config import get_settings
from app.llm import call_structured

LOW_FIT_THRESHOLD = 4  # icp_score below this (out of 10) stops the pipeline before drafting
MAX_CRITIC_REVISIONS = 2


class ProspectState(TypedDict, total=False):
    prospect_id: str
    name: str
    title: str | None
    company: str
    context: str | None
    icp_criteria: str | None
    sender_persona: str | None

    stage: Literal["new", "followup"]
    step: int  # 0 = initial outreach, 1+ = follow-up number

    research_profile: dict
    icp_score: int
    icp_reasoning: str

    draft_subject: str
    draft_body: str
    critic_notes: dict
    critic_attempts: int
    revision_feedback: str | None

    human_decision: dict
    final_subject: str
    final_body: str
    sent_gmail_message_id: str
    sent_gmail_thread_id: str


# --------------------------------------------------------------------------- research

def research_node(state: ProspectState) -> dict:
    tavily = TavilyClient(api_key=get_settings().tavily_api_key)

    person_query = f"{state['name']} {state.get('title') or ''} {state['company']}".strip()
    person_results = tavily.search(query=person_query, search_depth="advanced", max_results=5)
    company_results = tavily.search(
        query=f"{state['company']} company news funding product", max_results=5
    )

    sources = person_results.get("results", []) + company_results.get("results", [])
    research_blob = "\n\n".join(f"[{r['title']}] ({r['url']})\n{r['content']}" for r in sources)

    profile = call_structured(
        system=(
            "You are a sales research analyst. Given raw web search snippets about a "
            "prospect and their company, extract a factual, structured profile. Only "
            "include claims that are actually supported by the provided snippets -- "
            "if something isn't mentioned, omit it rather than guessing."
        ),
        user=(
            f"Prospect: {state['name']}, {state.get('title') or 'unknown title'} at {state['company']}.\n"
            f"User-supplied context: {state.get('context') or 'none'}\n\n"
            f"Web search results:\n{research_blob or 'No results found.'}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "role_summary": {"type": "string", "description": "What this person's role likely involves"},
                "company_summary": {"type": "string"},
                "recent_triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recent news, funding, launches, hiring pushes -- anything timely to reference",
                },
                "likely_pain_points": {"type": "array", "items": {"type": "string"}},
                "sources": {"type": "array", "items": {"type": "string"}, "description": "URLs actually used"},
            },
            "required": ["role_summary", "company_summary", "recent_triggers", "likely_pain_points"],
        },
    )
    return {"research_profile": profile}


# ------------------------------------------------------------------------------ score

def score_node(state: ProspectState) -> dict:
    result = call_structured(
        system=(
            "You score how well a sales prospect matches an ideal customer profile "
            "(ICP). Be honest and use the full 1-10 range -- most real leads are "
            "mediocre fits; reserve 8+ for prospects that clearly match."
        ),
        user=(
            f"ICP criteria: {state.get('icp_criteria') or 'General B2B software buyer.'}\n\n"
            f"Prospect profile:\n{json.dumps(state['research_profile'], indent=2)}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "score": {"type": "integer", "minimum": 1, "maximum": 10},
                "reasoning": {"type": "string"},
            },
            "required": ["score", "reasoning"],
        },
    )
    return {"icp_score": result["score"], "icp_reasoning": result["reasoning"]}


def route_after_score(state: ProspectState) -> str:
    if state["icp_score"] < LOW_FIT_THRESHOLD:
        return "end"
    return "draft"


# ----------------------------------------------------------------------------- draft

def draft_node(state: ProspectState) -> dict:
    step = state.get("step", 0)

    prior_email = None
    if step > 0:
        prior_email = db.fetch_one(
            "select subject, body from emails where prospect_id = %s and step = %s and status = 'sent'"
            " order by created_at desc limit 1",
            (state["prospect_id"], step - 1),
        )

    instructions = (
        f"Write a short, specific, non-generic cold outreach email to {state['name']} at "
        f"{state['company']}. Ground every specific claim in the research profile below -- "
        "do not invent facts. No more than 130 words. No subject-line clickbait."
    )
    if step > 0 and prior_email:
        instructions = (
            f"Write follow-up #{step} to a prospect who has not replied to the email below. "
            "Keep it short (under 80 words), add one new angle or piece of value, do not "
            "repeat the first email verbatim, and make it easy to ignore gracefully.\n\n"
            f"Original email:\nSubject: {prior_email['subject']}\n{prior_email['body']}"
        )

    feedback_note = ""
    if state.get("revision_feedback"):
        feedback_note = f"\n\nRevise addressing this feedback: {state['revision_feedback']}"

    result = call_structured(
        system=(
            f"You are an SDR writing outreach on behalf of the sender. Sender persona/tone: "
            f"{state.get('sender_persona') or 'professional, direct, friendly'}. {instructions}{feedback_note}"
        ),
        user=f"Research profile:\n{json.dumps(state['research_profile'], indent=2)}",
        input_schema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["subject", "body"],
        },
    )
    return {
        "draft_subject": result["subject"],
        "draft_body": result["body"],
        "revision_feedback": None,
    }


# ---------------------------------------------------------------------------- critic

def critic_node(state: ProspectState) -> dict:
    result = call_structured(
        system=(
            "You are a strict reviewer of cold outreach emails. Check for: (1) any claim "
            "not supported by the research profile provided (hallucination), (2) spammy "
            "language or trigger words, (3) excessive length or generic filler. Be picky."
        ),
        user=(
            f"Research profile:\n{json.dumps(state['research_profile'], indent=2)}\n\n"
            f"Email subject: {state['draft_subject']}\nEmail body:\n{state['draft_body']}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["passed", "issues"],
        },
    )
    attempts = state.get("critic_attempts", 0) + 1
    feedback = "; ".join(result["issues"]) if not result["passed"] else None
    return {"critic_notes": result, "critic_attempts": attempts, "revision_feedback": feedback}


def route_after_critic(state: ProspectState) -> str:
    if state["critic_notes"]["passed"] or state.get("critic_attempts", 0) >= MAX_CRITIC_REVISIONS:
        return "approval"
    return "revise"


# --------------------------------------------------------------------------- approval

def human_approval_node(state: ProspectState) -> dict:
    decision = interrupt(
        {
            "prospect_id": state["prospect_id"],
            "step": state.get("step", 0),
            "subject": state["draft_subject"],
            "body": state["draft_body"],
            "icp_score": state.get("icp_score"),
            "critic_notes": state.get("critic_notes"),
        }
    )
    if decision.get("action") == "approve":
        return {
            "human_decision": decision,
            "final_subject": decision.get("edited_subject") or state["draft_subject"],
            "final_body": decision.get("edited_body") or state["draft_body"],
        }
    return {
        "human_decision": decision,
        "revision_feedback": decision.get("rejection_reason") or "Reviewer rejected this draft.",
        "critic_attempts": 0,
    }


def route_after_approval(state: ProspectState) -> str:
    return "send" if state["human_decision"]["action"] == "approve" else "revise"


# ------------------------------------------------------------------------------ send

def send_node(state: ProspectState) -> dict:
    from app.gmail import send_email  # local import: avoids a hard import-time dependency loop

    email_id = state["human_decision"]["email_id"]
    prospect = db.fetch_one(
        "select email from prospects where id = %s", (state["prospect_id"],)
    )

    prior_thread_id = None
    step = state.get("step", 0)
    if step > 0:
        prior = db.fetch_one(
            "select gmail_thread_id from emails"
            " where prospect_id = %s and step = %s and status = 'sent' order by created_at desc limit 1",
            (state["prospect_id"], step - 1),
        )
        prior_thread_id = prior["gmail_thread_id"] if prior else None

    send_result = send_email(
        to_email=prospect["email"],
        subject=state["final_subject"],
        body=state["final_body"],
        email_id=email_id,
        gmail_thread_id=prior_thread_id,
    )
    return {
        "sent_gmail_message_id": send_result["message_id"],
        "sent_gmail_thread_id": send_result["thread_id"],
    }


# --------------------------------------------------------------------------- routing

def route_entry(state: ProspectState) -> str:
    return "research" if state["stage"] == "new" else "draft"


_checkpointer_cm = None
checkpointer: PostgresSaver | None = None
_graph = None


def init_checkpointer() -> None:
    global _checkpointer_cm, checkpointer, _graph
    if checkpointer is not None:
        return
    _checkpointer_cm = PostgresSaver.from_conn_string(get_settings().database_url)
    checkpointer = _checkpointer_cm.__enter__()
    checkpointer.setup()
    _graph = _build_graph(checkpointer)


def close_checkpointer() -> None:
    global _checkpointer_cm, checkpointer, _graph
    if _checkpointer_cm is not None:
        _checkpointer_cm.__exit__(None, None, None)
    _checkpointer_cm = None
    checkpointer = None
    _graph = None


def _build_graph(checkpointer: PostgresSaver):
    builder = StateGraph(ProspectState)
    builder.add_node("research", research_node)
    builder.add_node("score", score_node)
    builder.add_node("draft", draft_node)
    builder.add_node("critic", critic_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("send", send_node)

    builder.add_conditional_edges(START, route_entry, {"research": "research", "draft": "draft"})
    builder.add_edge("research", "score")
    builder.add_conditional_edges("score", route_after_score, {"draft": "draft", "end": END})
    builder.add_edge("draft", "critic")
    builder.add_conditional_edges("critic", route_after_critic, {"approval": "human_approval", "revise": "draft"})
    builder.add_conditional_edges("human_approval", route_after_approval, {"send": "send", "revise": "draft"})
    builder.add_edge("send", END)

    return builder.compile(checkpointer=checkpointer)


def get_graph():
    if _graph is None:
        raise RuntimeError("Graph checkpointer not initialized; call init_checkpointer() on startup")
    return _graph


def get_checkpointer() -> PostgresSaver:
    if checkpointer is None:
        raise RuntimeError("Graph checkpointer not initialized; call init_checkpointer() on startup")
    return checkpointer


def sync_after_run(prospect_id: str, thread_id: str, step: int) -> None:
    """Call after every graph.invoke() for this thread. Reads the checkpointed state
    back out and writes whatever changed to Postgres, so the rest of the app (API
    responses, the frontend, cron) only ever has to look at plain tables and never
    has to know how to read a LangGraph checkpoint itself."""

    graph = get_graph()
    snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
    values = snapshot.values
    paused = bool(snapshot.next)  # non-empty `next` means the graph is parked at an interrupt

    if paused:
        db.execute(
            """
            insert into emails (prospect_id, step, subject, body, critic_notes, status)
            values (%(prospect_id)s, %(step)s, %(subject)s, %(body)s, %(critic_notes)s, 'draft')
            on conflict (prospect_id, step) do update set
                subject = excluded.subject, body = excluded.body,
                critic_notes = excluded.critic_notes, status = 'draft'
            """,
            {
                "prospect_id": prospect_id,
                "step": step,
                "subject": values["draft_subject"],
                "body": values["draft_body"],
                "critic_notes": db.Jsonb(values.get("critic_notes")),
            },
        )
        db.execute(
            "update prospects set status = 'pending_approval', research_profile = %s,"
            " icp_score = %s, icp_reasoning = %s, updated_at = now() where id = %s",
            (
                db.Jsonb(values.get("research_profile")),
                values.get("icp_score"),
                values.get("icp_reasoning"),
                prospect_id,
            ),
        )
        return

    if values.get("sent_gmail_message_id"):
        db.execute(
            "update emails set status = 'sent', sent_at = now(), gmail_message_id = %s,"
            " gmail_thread_id = %s where prospect_id = %s and step = %s",
            (values["sent_gmail_message_id"], values["sent_gmail_thread_id"], prospect_id, step),
        )
        campaign = db.fetch_one(
            "select c.followup_delay_hours from campaigns c"
            " join prospects p on p.campaign_id = c.id where p.id = %s",
            (prospect_id,),
        )
        db.execute(
            "update prospects set status = 'awaiting_reply', followups_sent = followups_sent + 1,"
            " next_action_at = now() + (%s || ' hours')::interval, updated_at = now() where id = %s",
            (campaign["followup_delay_hours"], prospect_id),
        )
        return

    # Graph reached END without ever sending: the score node stopped it as a low-fit lead.
    db.execute(
        "update prospects set status = 'stopped_low_fit', research_profile = %s,"
        " icp_score = %s, icp_reasoning = %s, updated_at = now() where id = %s",
        (
            db.Jsonb(values.get("research_profile")),
            values.get("icp_score"),
            values.get("icp_reasoning"),
            prospect_id,
        ),
    )
