"""Pydantic request/response schemas shared across routers."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ICPProfileCreate(BaseModel):
    name: str
    criteria: str  # e.g. "B2B SaaS companies, 50-500 employees, engineering or ops leaders"


class ICPProfileOut(ICPProfileCreate):
    id: UUID
    created_at: datetime


class CampaignCreate(BaseModel):
    name: str
    icp_profile_id: UUID | None = None
    sender_persona: str | None = None
    followup_count: int = 2
    followup_delay_hours: int = 72


class CampaignOut(CampaignCreate):
    id: UUID
    created_at: datetime
    discovery_status: str | None = None  # null | "running" | "done" | "no_candidates_found" | "error"


class ProspectCreate(BaseModel):
    name: str
    title: str | None = None
    company: str
    email: str
    context: str | None = None  # LinkedIn URL, referral note, anything the user already knows


class ProspectOut(BaseModel):
    id: UUID
    campaign_id: UUID
    name: str
    title: str | None
    company: str
    email: str | None  # null for AI-discovered candidates awaiting human review (status="discovered")
    context: str | None
    research_profile: dict | None
    icp_score: int | None
    icp_reasoning: str | None
    status: str
    followups_sent: int
    next_action_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmailOut(BaseModel):
    id: UUID
    prospect_id: UUID
    step: int
    subject: str
    body: str
    critic_notes: dict | None
    status: str
    sent_at: datetime | None
    created_at: datetime


class ApprovalDecision(BaseModel):
    action: str  # "approve" | "reject"
    edited_subject: str | None = None
    edited_body: str | None = None
    rejection_reason: str | None = None  # fed back to the drafting node on reject
