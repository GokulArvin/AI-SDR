import type {
  Campaign,
  CampaignAnalytics,
  Email,
  ICPProfile,
  Prospect,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL!;

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---- ICP profiles
export const listICPProfiles = () => apiFetch<ICPProfile[]>("/icp-profiles");
export const createICPProfile = (body: { name: string; criteria: string }) =>
  apiFetch<ICPProfile>("/icp-profiles", { method: "POST", body: JSON.stringify(body) });
export const deleteICPProfile = (id: string) =>
  apiFetch<void>(`/icp-profiles/${id}`, { method: "DELETE" });

// ---- Campaigns
export const listCampaigns = () => apiFetch<Campaign[]>("/campaigns");
export const createCampaign = (body: {
  name: string;
  icp_profile_id: string | null;
  sender_persona: string | null;
  followup_count: number;
  followup_delay_hours: number;
}) => apiFetch<Campaign>("/campaigns", { method: "POST", body: JSON.stringify(body) });
export const getCampaign = (id: string) => apiFetch<Campaign>(`/campaigns/${id}`);
export const getCampaignAnalytics = (campaignId: string) =>
  apiFetch<CampaignAnalytics>(`/campaigns/${campaignId}/analytics`);
export const deleteCampaign = (id: string) =>
  apiFetch<void>(`/campaigns/${id}`, { method: "DELETE" });

// ---- Prospects
export const listProspects = (campaignId: string) =>
  apiFetch<Prospect[]>(`/campaigns/${campaignId}/prospects`);
export const createProspect = (
  campaignId: string,
  body: { name: string; title: string | null; company: string; email: string; context: string | null }
) => apiFetch<Prospect>(`/campaigns/${campaignId}/prospects`, { method: "POST", body: JSON.stringify(body) });
export const getProspect = (id: string) => apiFetch<Prospect>(`/prospects/${id}`);
export const listProspectEmails = (id: string) => apiFetch<Email[]>(`/prospects/${id}/emails`);
export const deleteProspect = (id: string) => apiFetch<void>(`/prospects/${id}`, { method: "DELETE" });

// ---- Discovery
export const discoverProspects = (campaignId: string) =>
  apiFetch<Campaign>(`/campaigns/${campaignId}/discover`, { method: "POST" });
export const startOutreach = (
  prospectId: string,
  body: { name: string; title: string | null; company: string; email: string; context: string | null }
) => apiFetch<Prospect>(`/prospects/${prospectId}/start-outreach`, { method: "POST", body: JSON.stringify(body) });

// ---- Approvals
export const listApprovals = () => apiFetch<Prospect[]>("/approvals");
export const submitApproval = (
  prospectId: string,
  body:
    | { action: "approve"; edited_subject: string | null; edited_body: string | null }
    | { action: "reject"; rejection_reason: string | null }
) => apiFetch<Prospect>(`/prospects/${prospectId}/approval`, { method: "POST", body: JSON.stringify(body) });

// ---- Gmail
export const getGmailStatus = () =>
  apiFetch<{ connected: boolean; email_address: string | null }>("/gmail/status");
export const getGmailConnectUrl = () =>
  apiFetch<{ authorization_url: string }>("/gmail/connect");
