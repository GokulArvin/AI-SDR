-- AI-SDR core schema. Run this in the Supabase SQL editor (or `psql $DATABASE_URL -f`).
-- Single-tenant app: no per-user scoping, the backend is the only writer.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Ideal-customer-profile definitions, used by the ICP-scoring graph node.
create table icp_profiles (
    id          uuid primary key default gen_random_uuid(),
    name        text not null,
    criteria    text not null,   -- free-text description the LLM scores prospects against
    created_at  timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
create table campaigns (
    id                  uuid primary key default gen_random_uuid(),
    name                text not null,
    icp_profile_id      uuid references icp_profiles(id) on delete set null,
    sender_persona       text,        -- how the agent should introduce/sign off, tone guidance
    followup_count       int not null default 2,
    followup_delay_hours int not null default 72,
    created_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- The one connected Gmail mailbox (single-tenant app: at most one row ever exists).
-- refresh_token is Fernet-encrypted before storage (see gmail.py) since it's a
-- long-lived credential.
create table gmail_connections (
    id                uuid primary key default gen_random_uuid(),
    email_address      text not null,
    refresh_token_enc  text not null,
    access_token       text,
    token_expiry       timestamptz,
    created_at        timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
create table prospects (
    id               uuid primary key default gen_random_uuid(),
    campaign_id      uuid not null references campaigns(id) on delete cascade,
    name             text not null,
    title            text,
    company          text not null,
    email            text not null, -- prospect's email address -- required, this is who we send to
    context          text,          -- free-text notes the user supplies (LinkedIn URL, how they found this lead, etc.)
    research_profile jsonb,         -- structured output of the research node
    icp_score        int,
    icp_reasoning    text,
    status           text not null default 'pending',
    thread_id        text not null unique,  -- LangGraph checkpointer thread id
    followups_sent   int not null default 0,
    next_action_at   timestamptz,   -- when the wait node should be resumed (follow-up due time)
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

create index prospects_status_idx on prospects (status, next_action_at);

-- ---------------------------------------------------------------------------
create table emails (
    id               uuid primary key default gen_random_uuid(),
    prospect_id      uuid not null references prospects(id) on delete cascade,
    step             int not null,      -- 0 = initial outreach, 1+ = follow-up N
    subject          text not null,
    body             text not null,
    critic_notes     jsonb,
    status           text not null default 'draft',  -- draft | approved | sent
    gmail_message_id text,
    gmail_thread_id  text,
    sent_at          timestamptz,
    created_at       timestamptz not null default now(),
    -- one row per (prospect, step): re-drafts (critic revision or human rejection) update
    -- this row in place rather than accumulating duplicate draft rows for the same step.
    unique (prospect_id, step)
);

create index emails_prospect_idx on emails (prospect_id);

-- ---------------------------------------------------------------------------
create table email_events (
    id          uuid primary key default gen_random_uuid(),
    email_id    uuid not null references emails(id) on delete cascade,
    event_type  text not null,  -- opened | clicked | replied
    metadata    jsonb,
    occurred_at timestamptz not null default now()
);

create index email_events_email_idx on email_events (email_id);
