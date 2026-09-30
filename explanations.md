# AI-SDR — Technical Walkthrough

A complete technical tour of this project: what it does, how every part of it works,
the database schema, the frontend, and how to run/test it. Written to stand on its
own — this is currently the only documentation file in the repo.

---

## 1. What this project is

AI-SDR is an autonomous sales outreach agent. You define who you're targeting (an
Ideal Customer Profile — industry, role, location), and the system:

1. **Finds** candidate prospects matching that profile by searching the web
2. **Researches** each one you approve for outreach
3. **Scores** their fit against your ICP
4. **Drafts** a personalized cold email grounded in that research
5. **Critiques** its own draft for hallucinated claims or spammy language
6. **Pauses for human approval** before anything is sent
7. **Sends** via your own connected Gmail account, with open/click tracking
8. **Follows up automatically** on a schedule if there's no reply — stopping the
   moment the prospect actually replies

It's single-tenant by design (no login) — built to demonstrate a durable,
checkpointed multi-agent workflow, not a simple prompt-in/text-out wrapper.

---

## 2. Repo layout

```
AI-SDR/
├── backend/             FastAPI app, LangGraph pipeline, discovery, Gmail, migrations
│   ├── app/
│   │   ├── main.py          FastAPI app instance, CORS, startup/shutdown lifecycle
│   │   ├── config.py        Settings loaded from backend/.env (pydantic-settings)
│   │   ├── db.py            psycopg connection pool + query helpers (no ORM)
│   │   ├── models.py        Pydantic request/response schemas
│   │   ├── discovery.py     *** AI prospect discovery (Tavily + Gemini) ***
│   │   ├── graph.py         *** the per-prospect agent pipeline (LangGraph) ***
│   │   ├── llm.py           Gemini wrapper that forces structured JSON output
│   │   ├── gmail.py         Gmail OAuth2, sending, reply detection
│   │   ├── tracking.py      open-pixel / click-redirect embedding + event logging
│   │   └── routers/
│   │       ├── campaigns.py    ICP profiles, campaigns, prospects, discovery, approvals, analytics
│   │       ├── gmail_auth.py   /gmail/connect, /gmail/callback, /gmail/status
│   │       ├── tracking.py     /track/open/*, /track/click/* (public, unauthenticated)
│   │       └── cron.py         POST /cron/tick — the one scheduled entry point
│   ├── migrations/
│   │   ├── 0001_init.sql       core schema, single-tenant, no per-user scoping
│   │   └── 0002_discovery.sql  makes prospects.email nullable + campaigns.discovery_status
│   ├── test_pipeline.py        runs the graph against 2 hardcoded prospects, no HTTP
│   └── requirements.txt
└── frontend/            Next.js App Router UI
    ├── app/
    │   ├── dashboard/page.tsx               campaigns list + KPIs (the landing page)
    │   ├── campaigns/[id]/page.tsx           prospects, AI discovery review, manual add
    │   ├── campaigns/[id]/analytics/page.tsx  funnel + open/click rate for one campaign
    │   ├── approvals/page.tsx               inbox of prospects paused for review
    │   ├── approvals/[id]/page.tsx           the draft review/edit/approve/reject screen
    │   ├── settings/page.tsx                Gmail connect + ICP profile CRUD
    │   └── layout.tsx                       shell: sidebar + theme bootstrap script
    ├── components/       Sidebar, StatusBadge, ThemeToggle, PageTransition, ui.tsx (design system)
    ├── lib/api.ts         one function per backend endpoint, all HTTP traffic goes through here
    ├── lib/types.ts        TypeScript types that mirror backend/app/models.py by hand
    └── package.json
```

---

## 3. AI Prospect Discovery (`backend/app/discovery.py`)

The entry point into a campaign. Rather than requiring every prospect to be typed in
by hand, a campaign's ICP criteria (composed from Target Industry / Target Job Roles
/ Target Location, entered on the "New campaign" form) can be handed to an automatic
discovery step.

**`discover_candidates(icp_criteria, count=8)`** — a plain function, deliberately
*not* a LangGraph node (see §4 for why). It runs two Tavily searches (one company-
oriented, one people-oriented) against the ICP criteria text, concatenates the raw
snippets, and hands them to `llm.call_structured` with instructions to extract up to
`count` **real, named individuals actually mentioned in the snippets** — explicitly
told never to invent a person just to hit the requested count. It can legitimately
return fewer candidates than asked for, or none at all; that's treated as a normal
outcome, not an error, since this relies on general web search rather than a paid
contact database.

**How it's wired in** (`backend/app/routers/campaigns.py`):
- `POST /campaigns/{id}/discover` sets `campaigns.discovery_status = 'running'` and
  queues `_run_discovery` as a FastAPI background task (same pattern as the main
  pipeline's background invocation — a real Tavily+Gemini call takes seconds, so it
  can't block the HTTP response).
- `_run_discovery` calls `discover_candidates`, then inserts each result as an
  ordinary row in the existing `prospects` table with `status = 'discovered'` and
  `email = NULL` — reusing the entire existing prospects data model/API/UI rather
  than a parallel staging table. Sets `discovery_status` to `'done'` or
  `'no_candidates_found'` when finished, or `'error'` if the run itself failed.
- Discovered candidates are surfaced in the frontend's "Needs your review" section
  (see §7) — nothing is researched or emailed automatically. A human confirms/edits
  each candidate's email (discovery never guesses one) and clicks **Start outreach**,
  which calls `POST /prospects/{id}/start-outreach`. That endpoint updates the row
  with the confirmed details, flips `status` to `'researching'`, and calls the exact
  same `_enter_pipeline()` helper that manual "Add prospect" uses — so from that
  point on, a discovered prospect and a manually-added one run through **identical,
  unmodified pipeline code**.

**Why `email` had to become nullable** (`migrations/0002_discovery.sql`): a
discovered candidate found via web search won't reliably have a verified email
address. Rather than requiring one at insert time, `prospects.email` was changed to
nullable, and the requirement is enforced in application code instead — the one
endpoint that starts the real pipeline (`start-outreach`, and `create_prospect` for
manual entry) still requires `ProspectCreate.email: str`, a required field. The
schema permits a temporary null; the code guarantees one exists before anything that
could actually send.

---

## 4. The per-prospect agent pipeline (`backend/app/graph.py`)

Once a prospect (discovered-and-confirmed, or manually added) enters the real
pipeline, this is what runs. A single [LangGraph](https://github.com/langchain-ai/langgraph)
state graph, **one instance ("thread") per prospect**, checkpointed to Postgres so
its state survives restarts and can be paused/resumed across HTTP requests that are
minutes or days apart.

### Why discovery is a plain function, not part of this graph

`graph.py`'s `StateGraph` is checkpointed per single named prospect, and its
`interrupt()`-based human-approval step is built around approving *one* drafted
email — not inventing several new prospects out of nothing. Bending that model to
fan out into N not-yet-existing prospects would mean restructuring the
checkpoint/thread model this entire tested pipeline relies on. Instead, discovery
*feeds* candidates into this same, completely unmodified graph via the identical
entry mechanism manual prospect creation already used — zero changes to any node,
edge, or the state shape below.

### State shape (`ProspectState`, a `TypedDict`)

Prospect identity (`name`, `title`, `company`, `context`), campaign config
(`icp_criteria`, `sender_persona`), and the fields each node fills in as the run
progresses (`research_profile`, `icp_score`, `draft_subject`/`draft_body`,
`critic_notes`, `human_decision`, `sent_gmail_message_id`, ...).

### The nodes, in execution order

1. **`research_node`** — calls Tavily twice (the named person, then their company),
   concatenates the raw snippets, then hands them to Gemini with instructions to
   extract *only* facts actually present in the snippets (no guessing) into a
   structured profile: `role_summary`, `company_summary`, `recent_triggers`
   (news/funding/launches), and `likely_pain_points`.

2. **`score_node`** — Gemini scores the research profile 1–10 against the campaign's
   ICP criteria text (the same text discovery used to find this person, or whatever
   was set when a prospect was added manually). Told explicitly to use the full
   range rather than being generous.
   - **`route_after_score`**: if `icp_score < 4` (`LOW_FIT_THRESHOLD`), the graph
     routes straight to `END` — nothing gets drafted for a bad-fit lead. Otherwise it
     continues to `draft`.

3. **`draft_node`** — Gemini writes the actual email, grounded only in the research
   profile, ≤130 words, told not to invent facts. If this is a **follow-up**
   (`step > 0`), it instead looks up the previously *sent* email for the prior step
   and asks Gemini to write a short (<80 word) follow-up that adds a new angle
   rather than repeating itself. If the critic (below) rejected the previous
   attempt, its feedback is appended to the prompt as a revision instruction.

4. **`critic_node`** — a second, independent Gemini call reviews the draft for
   (a) any claim not backed by the research profile — hallucination — (b) spammy
   language/trigger words, (c) excessive length or generic filler. Returns
   `{passed: bool, issues: [...]}`.
   - **`route_after_critic`**: if `passed` is `false` and the graph has retried
     fewer than `MAX_CRITIC_REVISIONS` (2) times, it loops back to `draft_node` with
     the issues as feedback. Otherwise it proceeds to human approval regardless —
     the critic can block a *retry*, but never blocks a human from seeing and
     deciding on the final draft.

5. **`human_approval_node`** — calls LangGraph's `interrupt()`, genuinely pausing
   the graph's execution mid-run (the Python call stack is frozen, full state
   written to the Postgres checkpoint) until resumed with a `Command(resume=...)`
   payload. The surfaced payload includes the draft, critic verdict, and ICP score.
   - Resume with `{action: "approve", edited_subject?, edited_body?}` — an edit made
     in the UI, if any, wins over the original draft.
   - Resume with `{action: "reject", rejection_reason}` — the reason becomes the
     next `revision_feedback`, `critic_attempts` resets to 0, loops back to `draft`.
   - **`route_after_approval`**: approved drafts → `send`, rejected → `draft`.

6. **`send_node`** — looks up the prospect's email and (for follow-ups) the prior
   email's Gmail thread ID so follow-ups thread correctly, then calls
   `app/gmail.py`'s `send_email`. Reaching `END` after this node ends the graph
   invocation.

### Two different kinds of "waiting" — and why only one uses LangGraph

A prospect might sit for **days** waiting for a reply before a follow-up is due.
`interrupt()` isn't meant for that — it holds a live paused execution context, not a
multi-day sleep. So instead:

- After `send_node`, the graph run simply **ends**.
- `prospects.next_action_at` (a plain Postgres timestamp) records when it should be
  picked up again.
- `POST /cron/tick` (see §6) periodically re-invokes the *same* `thread_id` later
  with `{"stage": "followup", "step": N}` — LangGraph re-enters the graph, and
  because it's the same thread, previously checkpointed state (research, ICP score)
  is already there to reuse. The entry router (`route_entry`) sends
  `stage == "followup"` straight to `draft_node`, skipping research/scoring again.

**LangGraph's checkpointer owns in-run agent reasoning and the human-approval
pause; a plain Postgres column owns long-horizon scheduling.** No task queue is
needed — the "queue" is just "rows in `prospects` where `next_action_at` is due,"
swept once per cron tick.

### `sync_after_run` — bridging LangGraph state back to plain tables

After every `graph.invoke()`, this reads the just-updated checkpoint back out and
writes the relevant bits into ordinary `prospects`/`emails` tables — paused at
approval → upsert a `draft` email row, set `pending_approval`; ended having sent →
mark `sent`, set `awaiting_reply`, schedule `next_action_at`; ended without drafting
(low ICP score) → `stopped_low_fit`. This is the *only* place that translates
LangGraph's internal state into plain tables — nothing else in the codebase needs to
know how to read a LangGraph checkpoint.

### Checkpointer lifecycle

`init_checkpointer()`/`close_checkpointer()` (called from `main.py`'s FastAPI
`lifespan`) open/close a `PostgresSaver` connection and build the compiled graph
once at process startup — `checkpointer.setup()` also runs LangGraph's own
migration for its internal checkpoint tables (separate from the app's own tables).

---

## 5. Supporting backend modules

### `app/llm.py` — the Gemini wrapper

One function, `call_structured(system, user, input_schema)`. Calls Gemini
(**`gemini-3.1-flash-lite`** — see note below) with `response_mime_type="application/json"`
and an exact JSON Schema (`response_json_schema`) describing the shape wanted back.
This constrains the model's output at the token level, so there's no "the model
wrapped the JSON in a markdown fence" parsing failure to defend against. Every
structured LLM call in the codebase (research/score/draft/critic/discovery) goes
through this one function. `thinking_config=ThinkingConfig(thinking_budget=1)` is
set explicitly because Flash's default "dynamic thinking" can otherwise burn the
whole output-token budget on invisible reasoning tokens and return truncated JSON.

> **Model note**: originally `gemini-3.6-flash`. Switched to `gemini-3.1-flash-lite`
> after live testing showed `gemini-3.6-flash` and `gemini-3.8-flash` both
> consistently returning `503 UNAVAILABLE — high demand` from Google, while
> `gemini-3.1-flash-lite` responded reliably to the identical structured-output call
> pattern. Revisit if Google's availability changes.

### `app/gmail.py` — OAuth2, sending, reply polling

- **Why Gmail instead of a transactional ESP**: sends through the *user's own*
  Gmail account — no owned domain/DNS needed, mirrors real rep-facing tools
  (Yesware, Mixmax), and lets reply detection happen by polling the same Gmail
  thread instead of needing an inbound-parse webhook.
- **OAuth flow**: `get_authorization_url()` builds Google's consent URL and stashes
  the PKCE `code_verifier` in an in-memory dict keyed by the OAuth `state` nonce
  (`_pending_states`). `handle_oauth_callback()` exchanges the code, **checks that
  Google actually granted the `gmail.send`/`gmail.readonly` scopes** (not just
  whatever was requested — Google can silently grant fewer scopes than requested if
  a user misses a checkbox on its consent screen), then fetches the connected
  account's email and stores the connection.
- **`GmailScopeError`** — raised when the grant is missing required Gmail scopes,
  caught by *before* trying to call a Gmail API that would otherwise fail with an
  opaque 403.
- **Every failure path redirects, never raises to the browser** — Google redirects
  the browser directly to the backend's `/gmail/callback` (never through the
  frontend), so `gmail_auth.py`'s callback handler catches `GmailScopeError`,
  `ValueError` (invalid/expired OAuth state), `HttpError`, and any other exception,
  mapping each to a `gmail_error=<code>` query param on a redirect back to
  `/settings` — the frontend shows a plain, actionable message for each code
  (`insufficient_scope`, `invalid_state`, `google_api_error`, `unknown`) instead of
  ever surfacing a raw FastAPI error page.
- **Single-tenant**: `gmail_connections` never holds more than one row — a new
  connect flow deletes any existing row before inserting.
- **Token encryption**: the refresh token is encrypted at rest with
  `cryptography.fernet.Fernet` before being written to Postgres.
- **Sending**: `send_email()` builds a MIME HTML message (tracking pixel + rewritten
  links already embedded, see `tracking.py`), base64-encodes it, calls the Gmail
  API's `messages.send`. Passing a prior `threadId` threads follow-ups into the
  same Gmail conversation as the original email.
- **Reply detection**: `has_reply()` fetches a thread's message list and checks
  whether any message besides the one sent lacks the `SENT` label.

### `app/tracking.py` — self-hosted open/click tracking

`embed_tracking()` regex-rewrites every `href="https://..."` in the HTML body to
route through `/track/click/{email_id}?url=<original>`, and appends an invisible
`<img>` pointing at `/track/open/{email_id}.png`. `log_event()` writes rows to
`email_events`, later aggregated by the analytics endpoint into open/click rates.

### `app/db.py` — the data-access layer (no ORM)

A thin layer over `psycopg` (raw parameterized SQL) with a connection pool
(1–10 connections). No ORM — the schema is small and stable, queries are simple
CRUD plus a few joins. `check=check_connection` is set on the pool specifically
because Supabase's connection pooler silently drops idle connections. `Jsonb` is
re-exported so callers can wrap dict params for `jsonb` columns. Three helpers cover
everything: `fetch_one`, `fetch_all`, `execute`.

### `app/config.py` — settings

A `pydantic_settings.BaseSettings` subclass that loads `backend/.env`. Required
fields (`database_url`, `gemini_api_key`, `tavily_api_key`, `google_client_id`/
`secret`, `token_encryption_key`, `cron_secret`) have no defaults — the app won't
start without them. `get_settings()` is `lru_cache`d so `.env` is parsed once.

### `app/models.py` — Pydantic schemas

`ICPProfileCreate/Out`, `CampaignCreate/Out` (`CampaignOut` adds
`discovery_status: str | None`), `ProspectCreate` (still requires `email: str` —
the one thing discovery can't skip), `ProspectOut` (`email: str | None`, nullable to
represent discovered-but-unconfirmed candidates), `EmailOut`, `ApprovalDecision`.

### `app/main.py` — app wiring

Builds the `FastAPI` app, registers CORS, mounts all four routers, defines the
`lifespan` context manager that opens the DB pool + LangGraph checkpointer on
startup and closes both on shutdown. `GET /health` → `{"status": "ok"}`.

---

## 6. The API surface (`app/routers/`)

### `campaigns.py` — core domain CRUD + discovery (one file: shared tables/flow)

| Method & path | What it does |
|---|---|
| `POST /icp-profiles`, `GET /icp-profiles` | create/list ICP text profiles |
| `DELETE /icp-profiles/{id}` | delete; campaigns referencing it fall back to `null` (`ON DELETE SET NULL`) |
| `POST /campaigns` | create a campaign (name, optional ICP, sender persona, follow-up count/delay) |
| `GET /campaigns`, `GET /campaigns/{id}` | list / fetch one |
| `DELETE /campaigns/{id}` | deletes each prospect's LangGraph checkpoint thread first, then the row (cascade handles the rest) |
| **`POST /campaigns/{id}/discover`** | **kicks off AI prospect discovery** — sets `discovery_status = 'running'`, queues the background search |
| `POST /campaigns/{id}/prospects` | manual entry — inserts `status = 'researching'`, queues the pipeline via `_enter_pipeline` |
| `GET /campaigns/{id}/prospects` | list prospects (both `discovered` candidates and real pipeline prospects) |
| **`POST /prospects/{id}/start-outreach`** | **promotes a `discovered` candidate** — updates its fields (email required), flips to `'researching'`, queues the same pipeline entry as manual creation |
| `GET /prospects/{id}` | fetch one (frontend polls this while mid-pipeline) |
| `DELETE /prospects/{id}` | deletes the LangGraph thread, then the row |
| `GET /prospects/{id}/emails` | every drafted/sent email for a prospect, in step order |
| `GET /approvals` | every prospect currently `pending_approval`, oldest first — the approval inbox |
| `POST /prospects/{id}/approval` | validates `pending_approval`, builds a `Command(resume=...)`, queues resumption of the parked graph thread |
| `GET /campaigns/{id}/analytics` | funnel counts by status + `open_rate`/`click_rate` from `email_events` |

`_enter_pipeline(prospect_id, thread_id, campaign, icp_criteria, body, background_tasks)`
is the one shared function that builds `initial_state` and queues
`_invoke_and_sync` — both `create_prospect` (manual) and `start_outreach`
(AI-discovered) call it identically, so there is exactly one code path into the real
pipeline regardless of how a prospect originated.

`_invoke_and_sync` (background task): `graph.invoke()` then `sync_after_run()`. Any
exception (transient LLM/search API error, etc.) is caught, logged, and the
prospect is marked `status = 'error'` — visible on the dashboard rather than
silently stuck.

### `gmail_auth.py`

`GET /gmail/connect` → Google consent URL. `GET /gmail/callback` → exchanges the
code; **every** failure path redirects to `/settings?gmail_error=<code>` (see §5),
success redirects to `/settings?gmail_connected=<email>`. `GET /gmail/status` →
whether an account is connected and which email.

### `tracking.py`

Public, unauthenticated by design: `GET /track/open/{email_id}.png` serves a 1×1
GIF and logs `opened`; `GET /track/click/{email_id}` logs `clicked` and redirects.

### `cron.py` — the one scheduled entry point

`POST /cron/tick`, gated by an `X-Cron-Secret` header. Processed synchronously (tick
volume is small; easier to reason about and smoke-test with a plain curl call). For
every `awaiting_reply` prospect: checks for a reply via `gmail.has_reply`; if none
and `next_action_at` is due, either triggers the next follow-up (re-invokes the same
graph thread with `stage="followup"`) or marks `completed_no_response` once
`followup_count` is exhausted. A single prospect erroring doesn't stop the sweep.

---

## 7. The database (Supabase Postgres — hosted Postgres only, no Auth/Storage/Realtime used)

`pgcrypto` extension enabled for `gen_random_uuid()`. Two migration files, no ORM,
no auto-generated migrations.

| Table | Purpose | Notable columns |
|---|---|---|
| `icp_profiles` | Named, free-text ICP scoring rubrics | `criteria` (text handed to Gemini verbatim, for both scoring *and* discovery search queries) |
| `campaigns` | Groups prospects under one ICP + follow-up cadence | `icp_profile_id` (`ON DELETE SET NULL`), `sender_persona`, `followup_count`, `followup_delay_hours`, **`discovery_status`** (`0002`: null / running / done / no_candidates_found / error) |
| `gmail_connections` | The one connected mailbox (never >1 row) | `refresh_token_enc` (Fernet-encrypted), `access_token`, `token_expiry` |
| `prospects` | One row per prospect, the central entity | `research_profile jsonb`, `icp_score`, `status` (now includes `discovered`), `thread_id` (unique — LangGraph thread key), `followups_sent`, `next_action_at`, **`email` (nullable as of `0002`** — null for AI-discovered candidates awaiting human confirmation). Indexed on `(status, next_action_at)` |
| `emails` | One row per (prospect, step) | `step` (0 = initial, 1+ = follow-up N), `critic_notes jsonb`, `status`, `gmail_message_id`, `gmail_thread_id`. `unique(prospect_id, step)` — revisions update in place |
| `email_events` | Every open/click event | `event_type` (opened/clicked/replied), `metadata jsonb` |

Foreign keys cascade downward (`campaigns → prospects → emails → email_events`) via
plain SQL `ON DELETE CASCADE` — except LangGraph's own checkpoint rows (separate
tables created by `checkpointer.setup()`), which the app deletes explicitly via
`checkpointer.delete_thread(...)` before the SQL delete.

**No per-user scoping anywhere** — single operator, one connected mailbox, no login.

---

## 8. The frontend (Next.js App Router, Tailwind v4, no component library)

### Pages

- **`/` →** redirects to `/dashboard`. No login screen.
- **`/dashboard`** — campaigns list. KPI tiles (total prospects, awaiting review,
  awaiting reply, reply rate), a segmented status bar per campaign card (now
  includes `discovered` as its own segment), and "New campaign" form collecting
  **Campaign Name, Target Industry, Target Job Roles, Target Location** — these are
  composed client-side into one free-text string and posted as a new ICP profile
  (`"<Campaign Name> — ICP"`) behind the scenes, so the campaign always references
  real, stored scoring criteria without the user having to manage ICP profiles
  separately. Follow-up count/delay and sender persona are sent as fixed defaults
  (2 follow-ups, 72h, no persona) rather than shown on this form.
- **`/campaigns/[id]`** — the main working view for one campaign:
  - **Find prospects** button → `POST /campaigns/{id}/discover`, then polls
    `getCampaign` every 4s while `discovery_status === "running"`.
  - **"Needs your review"** section — any prospect with `status === "discovered"`,
    rendered by a dedicated `DiscoveredCandidateCard`: name/title/company/context,
    an editable email field (required before the button enables), **Start
    outreach**, and a dismiss button.
  - Manual **Add prospect** form — Name/Title/Company/Email fields use
    auto-growing `Textarea`s (an `autoGrow` `onInput` handler resizes the box to
    fit content, so long entries wrap and grow the field instead of scrolling
    horizontally out of view — the one native trade-off is losing the browser's
    built-in email-format validation/mobile keyboard on the Email field, since
    that's a `Textarea` now rather than `<input type="email">`).
  - The existing prospect list (everyone *not* `discovered`) polls every 4s while
    any prospect is `researching`/`sending`.
- **`/campaigns/[id]/analytics`** — emails sent, open rate, click rate, horizontal
  funnel bar of prospect counts per status.
- **`/approvals`** — inbox: every `pending_approval` prospect, oldest first.
- **`/approvals/[id]`** — review screen: editable subject/body pre-filled with the
  draft, critic pass/fail + issues, ICP score + reasoning, full research profile.
  "Approve & send" only sends edited fields if they actually differ from the
  original draft. "Reject / revise" feeds a textarea straight back into `draft_node`.
- **`/settings`** — Gmail connect/reconnect (redirects the browser to Google's
  consent screen and back), a **red error banner** if the connect flow failed
  (reads the `gmail_error` query param, maps it through a small message lookup —
  see §5), and ICP profile CRUD.

### Components

- **`ui.tsx`** — hand-rolled design system: `Button` (primary/outline/ghost/danger,
  loading spinner), `Card`, `Input`/`Textarea`/`Field` (shared focus-ring styling),
  `PageHeader`, `EmptyState`, `LoadingState`. Tailwind utilities + `lucide-react`
  icons only, no external UI library.
- **`StatusBadge.tsx`** — maps each status (including `discovered`) to a color
  (text+bg for badges, solid-fill for progress-bar segments) and defines the
  canonical display order (`STAGE_ORDER`, `discovered` first) used by the
  dashboard's segmented bars.
- **`Sidebar.tsx`** — persistent nav (Campaigns/Approvals/Settings) with live
  counts refetched on every route change.
- **`ThemeToggle.tsx`** — light/dark toggle via `localStorage` + `data-theme` on
  `<html>`; an inline `<script>` in `layout.tsx`'s `<head>` applies the stored
  theme before React hydrates.
- **`PageTransition.tsx`** — `key={pathname}` wrapper so route changes get a fresh
  mount and CSS transition.

### Data layer

- **`lib/types.ts`** — `ProspectStatus` now includes `"discovered"`;
  `Prospect.email: string | null`; `Campaign.discovery_status: DiscoveryStatus`.
  Manually kept in sync with `backend/app/models.py`, no codegen.
- **`lib/api.ts`** — one wrapped-`fetch` function (`apiFetch`) plus one named export
  per endpoint, including `discoverProspects(campaignId)` and
  `startOutreach(prospectId, body)`.

No global state library — every page owns its data via `useState`/`useEffect` and
refetches directly from the API.

---

## 9. A prospect's full lifecycle (status state machine)

```
 discovered (AI found, awaiting your review)
     │  (you confirm email → Start outreach)
     ▼
 researching  →  pending_approval  →  sending  →  awaiting_reply
     │                                                  │  │
     └──(icp_score < 4)──→ stopped_low_fit               │  └──(no reply, follow-ups
                                                           │      left)──→ back to
(any pipeline exception)──→ error ←───────────────────────┘      pending_approval
                                                           │
                                          (reply detected)─┼──→ replied
                                                           │
                                    (no reply, follow-ups │
                                     exhausted)────────────┴──→ completed_no_response
```

- `discovered` is the only state that never touches the LangGraph pipeline at all —
  it's pure data sitting in `prospects` waiting for a human decision.
- `researching`/`sending` are states where a **background task** is actively
  running the graph — the frontend polls during these.
- `pending_approval` waits on a **human** — the LangGraph `interrupt()` parked state.
- `awaiting_reply` waits on **calendar time**, resolved by the next cron tick.

---

## 10. How to run it locally

```powershell
# Backend (from backend/, using the repo-root .venv)
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
# Check http://localhost:8000/health -> {"status":"ok"}

# Frontend (new terminal, from frontend/)
npm run dev
# Open http://localhost:3000 -- redirects straight to the dashboard
```

Both `backend/.env` and `frontend/.env` are expected to already be filled in with
real Supabase/Gemini/Tavily/Google OAuth credentials. `uvicorn --reload` has been
unreliable in this environment (the worker can keep serving stale code under the
same PID after an edit) — after backend changes, kill the process and start a fresh
`uvicorn` without `--reload` rather than trusting the auto-reloader.

**No-UI pipeline sanity check** (bypasses the API entirely, useful for judging
research/drafting quality directly):
```powershell
cd backend
..\.venv\Scripts\python.exe test_pipeline.py
```

**Testing follow-ups without waiting days** — manually trigger the cron sweep:
```powershell
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/cron/tick" `
  -Headers @{ "X-Cron-Secret" = "<CRON_SECRET from backend/.env>" }
```

---

## 11. Tech stack

**Backend**: `fastapi` + `uvicorn` (HTTP layer) · `pydantic`/`pydantic-settings`
(schemas + `.env` config) · `psycopg[binary,pool]` (raw SQL driver + connection
pool, no ORM) · `langgraph` + `langgraph-checkpoint-postgres` (the agent graph and
its Postgres-backed durable execution) · `google-genai` (Gemini client, model
`gemini-3.1-flash-lite`) · `tavily-python` (web research + discovery) ·
`google-api-python-client`/`google-auth`/`google-auth-oauthlib` (Gmail API + OAuth2)
· `cryptography` (Fernet encryption for the stored Gmail refresh token).

**Frontend**: `next` (App Router, Turbopack dev server) + `react`/`react-dom` ·
`tailwindcss` v4, hand-rolled design system, no component library · `lucide-react`
(the only icon set). No state-management or data-fetching library beyond a thin
`fetch` wrapper.

**Infrastructure**: Supabase (Postgres hosting only) · Google Cloud (Gmail OAuth
client) · Google AI Studio (Gemini API key, free tier) · Tavily (search API, free
tier). No task queue — see §4 for why the LangGraph checkpointer + a cron-swept
timestamp column cover both kinds of "waiting" this app needs.

---

## 12. Design decisions and known limitations worth knowing

- **Discovery quality depends on Tavily's web-search results, not a paid contact
  database.** Broad criteria surface more candidates than narrow ones; it may
  return zero for a very specific search. Emails are never guessed — always human-
  confirmed before anything enters the real send-capable pipeline.
- **Single-tenant, no auth, by design.** Every API route is open; fine on
  `localhost`, but deploying the backend publicly without a network restriction or
  auth layer would let anyone create campaigns or trigger sends through the
  connected Gmail account.
- **No unsubscribe/suppression-list handling** — acceptable for addresses you
  control during development; would need adding before real unsolicited outreach.
- **Gmail send-volume limits apply** since sending goes through a personal mailbox
  rather than a dedicated transactional-email domain.
- **`_pending_states` (OAuth PKCE tracking) is in-memory only** — any Gmail connect
  attempt in flight across a backend restart will fail on callback with
  `gmail_error=invalid_state`. Expected; just restart the connect flow fresh.
- **No automated test suite** (pytest/etc.) exists in this repo. `test_pipeline.py`
  is a manual quality-check script, not a CI-run assertion suite.
