// Mirrors backend/app/models.py

export interface ICPProfile {
  id: string;
  name: string;
  criteria: string;
  created_at: string;
}

export type DiscoveryStatus = "running" | "done" | "no_candidates_found" | "error" | null;

export interface Campaign {
  id: string;
  name: string;
  icp_profile_id: string | null;
  sender_persona: string | null;
  followup_count: number;
  followup_delay_hours: number;
  created_at: string;
  discovery_status: DiscoveryStatus;
}

export type ProspectStatus =
  | "discovered"
  | "researching"
  | "pending_approval"
  | "sending"
  | "awaiting_reply"
  | "replied"
  | "completed_no_response"
  | "stopped_low_fit"
  | "error";

export interface ResearchProfile {
  role_summary: string;
  company_summary: string;
  recent_triggers: string[];
  likely_pain_points: string[];
  sources?: string[];
}

export interface CriticNotes {
  passed: boolean;
  issues: string[];
}

export interface Prospect {
  id: string;
  campaign_id: string;
  name: string;
  title: string | null;
  company: string;
  email: string | null;
  context: string | null;
  research_profile: ResearchProfile | null;
  icp_score: number | null;
  icp_reasoning: string | null;
  status: ProspectStatus;
  followups_sent: number;
  next_action_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Email {
  id: string;
  prospect_id: string;
  step: number;
  subject: string;
  body: string;
  critic_notes: CriticNotes | null;
  status: "draft" | "approved" | "sent";
  sent_at: string | null;
  created_at: string;
}

export interface CampaignAnalytics {
  funnel: Record<string, number>;
  emails_sent: number;
  open_rate: number;
  click_rate: number;
}
