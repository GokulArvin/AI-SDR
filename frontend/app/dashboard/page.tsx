"use client";

import { ArrowRight, Megaphone, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { STAGE_ORDER, STATUS_FILL } from "@/components/StatusBadge";
import { Button, Card, EmptyState, Field, Input, LoadingState, PageHeader } from "@/components/ui";
import { createCampaign, createICPProfile, deleteCampaign, listApprovals, listCampaigns, listProspects } from "@/lib/api";
import type { Campaign, Prospect } from "@/lib/types";

function statusCounts(prospects: Prospect[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const p of prospects) counts[p.status] = (counts[p.status] ?? 0) + 1;
  return counts;
}

function railColor(counts: Record<string, number>): string {
  if (counts.error) return "bg-danger";
  if (counts.replied) return "bg-success";
  if (counts.pending_approval) return "bg-warning";
  return "bg-primary";
}

export default function DashboardPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [prospectsByCampaign, setProspectsByCampaign] = useState<Record<string, Prospect[]>>({});
  const [approvalCount, setApprovalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const refresh = () => {
    Promise.all([listCampaigns(), listApprovals()]).then(([c, approvals]) => {
      setCampaigns(c);
      setApprovalCount(approvals.length);
      setLoading(false);
      Promise.all(c.map((campaign) => listProspects(campaign.id))).then((lists) => {
        const byCampaign: Record<string, Prospect[]> = {};
        c.forEach((campaign, i) => (byCampaign[campaign.id] = lists[i]));
        setProspectsByCampaign(byCampaign);
      });
    });
  };

  useEffect(refresh, []);

  const allProspects = Object.values(prospectsByCampaign).flat();
  const awaitingReplyCount = allProspects.filter((p) => p.status === "awaiting_reply").length;
  const repliedCount = allProspects.filter((p) => p.status === "replied").length;
  const noResponseCount = allProspects.filter((p) => p.status === "completed_no_response").length;
  const replyRateDenominator = repliedCount + noResponseCount;
  const replyRate = replyRateDenominator > 0 ? repliedCount / replyRateDenominator : null;

  const onDeleteCampaign = async (e: React.MouseEvent, id: string, name: string) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete campaign "${name}"? This also deletes all its prospects and emails — this can't be undone.`)) return;
    await deleteCampaign(id);
    refresh();
  };

  return (
    <div>
      <PageHeader
        title="Campaigns"
        description="Each campaign pairs an ICP profile with a follow-up cadence for its prospects."
        actions={
          <Button icon={Plus} onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Cancel" : "New campaign"}
          </Button>
        }
      />

      {showForm && (
        <div className="mb-6">
          <NewCampaignForm
            onCreated={() => {
              setShowForm(false);
              refresh();
            }}
          />
        </div>
      )}

      {loading ? (
        <LoadingState />
      ) : campaigns.length === 0 ? (
        <EmptyState
          icon={Megaphone}
          title="No campaigns yet"
          description="Create a campaign to start adding prospects and generating outreach."
          action={
            !showForm && (
              <Button size="sm" icon={Plus} onClick={() => setShowForm(true)}>
                New campaign
              </Button>
            )
          }
        />
      ) : (
        <div className="flex flex-col gap-8">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <Kpi label="Total prospects" value={allProspects.length} />
            <Kpi label="Awaiting your review" value={approvalCount} />
            <Kpi label="Awaiting reply" value={awaitingReplyCount} />
            <Kpi label="Reply rate" value={replyRate === null ? "—" : `${(replyRate * 100).toFixed(0)}%`} />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {campaigns.map((c) => {
              const prospects = prospectsByCampaign[c.id];
              const counts = prospects ? statusCounts(prospects) : {};
              const total = prospects?.length ?? 0;
              const segments = STAGE_ORDER.filter((s) => counts[s]);

              return (
                <Link key={c.id} href={`/campaigns/${c.id}`}>
                  <Card className="h-full hover:border-primary/40 hover:shadow-md transition-all group overflow-hidden flex">
                    <div className={`w-1 shrink-0 ${railColor(counts)}`} />
                    <div className="p-5 flex-1 min-w-0">
                      <div className="flex items-start justify-between">
                        <div className="size-9 rounded-lg bg-primary/10 text-primary flex items-center justify-center mb-3">
                          <Megaphone className="size-4.5" />
                        </div>
                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button
                            onClick={(e) => onDeleteCampaign(e, c.id, c.name)}
                            aria-label={`Delete ${c.name}`}
                            className="p-1 rounded-md text-muted-foreground hover:text-danger hover:bg-danger-bg transition-colors"
                          >
                            <Trash2 className="size-4" />
                          </button>
                          <ArrowRight className="size-4 text-muted-foreground" />
                        </div>
                      </div>
                      <div className="font-medium">{c.name}</div>
                      <div className="text-sm text-muted-foreground mt-1 mb-3">
                        {c.followup_count} follow-up{c.followup_count === 1 ? "" : "s"} · every {c.followup_delay_hours}h
                      </div>

                      {total > 0 ? (
                        <>
                          <div className="flex h-1.5 rounded-full bg-muted overflow-hidden mb-2">
                            {segments.map((status) => (
                              <span
                                key={status}
                                className={STATUS_FILL[status]}
                                style={{ width: `${(counts[status] / total) * 100}%` }}
                              />
                            ))}
                          </div>
                          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                            {segments.map((status) => (
                              <span key={status} className="inline-flex items-center gap-1.5">
                                <span className={`size-1.5 rounded-full ${STATUS_FILL[status]}`} />
                                {counts[status]} {status.replaceAll("_", " ")}
                              </span>
                            ))}
                          </div>
                        </>
                      ) : (
                        <div className="text-xs text-muted-foreground">No prospects yet</div>
                      )}
                    </div>
                  </Card>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-4">
      <div className="text-[11px] uppercase tracking-wide font-semibold text-muted-foreground mb-2">{label}</div>
      <div className="text-2xl font-semibold tracking-tight font-mono tabular-nums">{value}</div>
    </Card>
  );
}

function NewCampaignForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [targetIndustry, setTargetIndustry] = useState("");
  const [targetRoles, setTargetRoles] = useState("");
  const [targetLocation, setTargetLocation] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      // The ICP-scoring node reads free-text criteria (see backend/app/graph.py
      // score_node) -- these three fields are just a friendlier way to fill that
      // text in, composed into one ICP profile behind the scenes so scoring keeps
      // working for prospects added to this campaign later (including follow-ups
      // drafted days after creation, long after this form submission is gone).
      const criteria = [
        targetIndustry && `Target industry: ${targetIndustry}.`,
        targetRoles && `Target job roles: ${targetRoles}.`,
        targetLocation && `Target location: ${targetLocation}.`,
      ]
        .filter(Boolean)
        .join(" ");

      let icpProfileId: string | null = null;
      if (criteria) {
        const icp = await createICPProfile({ name: `${name} — ICP`, criteria });
        icpProfileId = icp.id;
      }

      await createCampaign({
        name,
        icp_profile_id: icpProfileId,
        sender_persona: null,
        followup_count: 2,
        followup_delay_hours: 72,
      });
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Campaign name">
          <Input required placeholder="e.g. College Outreach Campaign" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Target industry">
          <Input placeholder="e.g. Higher Education" value={targetIndustry} onChange={(e) => setTargetIndustry(e.target.value)} />
        </Field>
        <Field label="Target job roles">
          <Input placeholder="e.g. Dean, Director, CIO" value={targetRoles} onChange={(e) => setTargetRoles(e.target.value)} />
        </Field>
        <Field label="Target location">
          <Input placeholder="e.g. India" value={targetLocation} onChange={(e) => setTargetLocation(e.target.value)} />
        </Field>
        <Button type="submit" loading={busy} className="self-start">
          Create campaign
        </Button>
      </form>
    </Card>
  );
}
