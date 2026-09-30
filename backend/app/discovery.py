"""AI prospect discovery: given a campaign's ICP criteria, search the web for real,
named people who plausibly match it -- so a campaign doesn't require every prospect to
be typed in by hand.

Deliberately a plain function, not a LangGraph node: graph.py's StateGraph is
checkpointed per single named prospect and its interrupt() is built around approving
one drafted email. Discovery instead *feeds* candidates into that same, unmodified
pipeline (see routers/campaigns.py's start_outreach) via the exact mechanism manual
"Add prospect" already uses -- no changes to the tested per-prospect graph.

Uses Tavily (the same search tool research_node already relies on), not a dedicated
contact-database API -- so results can be hit-or-miss for narrow criteria, and emails
are never guessed here; a human confirms one before a candidate enters the real
pipeline.
"""

from tavily import TavilyClient

from app.config import get_settings
from app.llm import call_structured


def discover_candidates(icp_criteria: str, count: int = 8) -> list[dict]:
    tavily = TavilyClient(api_key=get_settings().tavily_api_key)

    company_results = tavily.search(
        query=f"companies matching: {icp_criteria}", search_depth="advanced", max_results=8
    )
    people_results = tavily.search(
        query=f"{icp_criteria} name title LinkedIn", search_depth="advanced", max_results=8
    )
    sources = company_results.get("results", []) + people_results.get("results", [])
    research_blob = "\n\n".join(f"[{r['title']}] ({r['url']})\n{r['content']}" for r in sources)

    result = call_structured(
        system=(
            "You are a sales prospecting analyst. Given raw web search snippets, extract "
            f"up to {count} REAL, NAMED individuals who plausibly match the ideal-customer "
            "profile below. Only include people actually mentioned by name in the snippets "
            "-- never invent a person just to reach the requested count. If the snippets "
            "don't contain enough concrete named individuals, return fewer candidates, or "
            "none at all."
        ),
        user=f"ICP criteria: {icp_criteria}\n\nWeb search results:\n{research_blob or 'No results found.'}",
        input_schema={
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "title": {"type": "string"},
                            "company": {"type": "string"},
                            "context": {
                                "type": "string",
                                "description": "One sentence on why this person matched the ICP criteria",
                            },
                        },
                        "required": ["name", "company"],
                    },
                },
            },
            "required": ["candidates"],
        },
        max_tokens=2500,
    )
    return result["candidates"]
