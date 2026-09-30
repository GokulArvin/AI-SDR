-- AI prospect discovery: candidates found by web search won't reliably have a
-- verified email until a human confirms one, so it can no longer be required at
-- insert time. The real send pipeline still can't run without one -- that's
-- enforced in application code (the /prospects/{id}/start-outreach endpoint
-- requires it), not by the schema.
alter table prospects alter column email drop not null;

-- Tracks the state of the (single, at-a-time) discovery run for a campaign, so
-- the frontend has something to poll before any candidate rows exist yet. Same
-- plain-status-column convention as prospects.status / emails.status -- no
-- separate job-queue table.
alter table campaigns add column discovery_status text;
