"""Runs the agent pipeline against a couple of hardcoded prospects with no HTTP layer
involved, so research/scoring/drafting/critic quality can be checked directly before
testing through the API or UI. Needs a real .env (DB + Gemini + Tavily keys).

Usage:
    cd backend
    python test_pipeline.py
"""

import json
import uuid

from app import db
from app.graph import get_graph, init_checkpointer

TEST_PROSPECTS = [
    {
        "name": "Satya Nadella",
        "title": "CEO",
        "company": "Microsoft",
        "context": "Announced at a recent keynote that Copilot is being embedded across the Office suite.",
    },
    {
        "name": "A. Nobody",
        "title": "Intern",
        "company": "A tiny local bakery with no online presence",
        "context": None,
    },
]

ICP_CRITERIA = "Enterprise software companies with 1000+ employees actively investing in AI products."


def main() -> None:
    db.init_pool()
    init_checkpointer()
    graph = get_graph()

    for prospect in TEST_PROSPECTS:
        thread_id = str(uuid.uuid4())
        prospect_id = str(uuid.uuid4())
        print(f"\n{'=' * 70}\nRunning pipeline for {prospect['name']} @ {prospect['company']}\n{'=' * 70}")

        initial_state = {
            "prospect_id": prospect_id,
            "name": prospect["name"],
            "title": prospect["title"],
            "company": prospect["company"],
            "context": prospect["context"],
            "icp_criteria": ICP_CRITERIA,
            "sender_persona": "friendly, concise SDR at an AI sales tooling startup",
            "stage": "new",
            "step": 0,
        }

        graph.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values

        print(f"ICP score: {values.get('icp_score')} -- {values.get('icp_reasoning')}")
        if values.get("draft_subject"):
            print(f"\nSubject: {values['draft_subject']}\n\n{values['draft_body']}")
            print(f"\nCritic notes: {json.dumps(values.get('critic_notes'), indent=2)}")
            print(f"Paused for approval: {bool(snapshot.next)}")
        else:
            print("Pipeline stopped before drafting (low ICP fit) -- as expected for the bakery example.")

    db.close_pool()


if __name__ == "__main__":
    main()
