"use client";

import { BarChart3, Plus, Search, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { Button, Card, EmptyState, Field, Input, LoadingState, PageHeader, Textarea } from "@/components/ui";
import { createProspect, deleteProspect, discoverProspects, getCampaign, listProspects, startOutreach } from "@/lib/api";
import type { Campaign, Prospect } from "@/lib/types";

const DISCOVERY_MESSAGES: Record<string, string> = {
  no_candidates_found: "No candidates found for this campaign's criteria — try broadening the target industry, role, or location.",
  error: "Something went wrong while searching for prospects. Try again.",
};

export default function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [discovering, setDiscovering] = useState(false);

  const refreshCampaign = useCallback(() => {
    getCampaign(id).then(setCampaign);
  }, [id]);

  useEffect(refreshCampaign, [refreshCampaign]);

  const refresh = useCallback(() => {
    listProspects(id).then((p) => {
      setProspects(p);
      setLoading(false);
    });
  }, [id]);

  useEffect(refresh, [refresh]);
  // Poll while any prospect is still being researched/sent so the UI reflects
  // background-task progress without the user needing to refresh manually.
  useEffect(() => {
    const active = prospects.some((p) => p.status === "researching" || p.status === "sending");
    if (!active) return;
    const interval = setInterval(refresh, 4000);
    return () => clearInterval(interval);
  }, [prospects, refresh]);

  // Poll while a "Find prospects" discovery run is in progress -- a real Tavily +
  // Gemini call, same reasoning as the prospect-status poll above.
  useEffect(() => {
    if (campaign?.discovery_status !== "running") return;
    const interval = setInterval(() => {
      refreshCampaign();
      refresh();
    }, 4000);
    return () => clearInterval(interval);
  }, [campaign?.discovery_status, refreshCampaign, refresh]);

  const onFindProspects = async () => {
    setDiscovering(true);
    try {
      setCampaign(await discoverProspects(id));
    } finally {
      setDiscovering(false);
    }
  };

  const onDeleteProspect = async (id: string, name: string) => {
    if (!confirm(`Delete prospect "${name}"? This also deletes their drafted/sent emails — this can't be undone.`)) return;
    await deleteProspect(id);
    refresh();
  };

  const onDismissCandidate = async (id: string, name: string) => {
    if (!confirm(`Dismiss "${name}"? They won't be contacted.`)) return;
    await deleteProspect(id);
    refresh();
  };

  const discoveredCandidates = prospects.filter((p) => p.status === "discovered");
  const pipelineProspects = prospects.filter((p) => p.status !== "discovered");
  const isDiscovering = discovering || campaign?.discovery_status === "running";

  return (
    <div>
      <PageHeader
        title={campaign ? campaign.name : "Prospects"}
        description={campaign ? "Prospects in this campaign." : undefined}
        back={{ href: "/dashboard", label: "Campaigns" }}
        actions={
          <>
            <Link href={`/campaigns/${id}/analytics`}>
              <Button variant="outline" icon={BarChart3}>
                Analytics
              </Button>
            </Link>
            <Button variant="outline" icon={Search} loading={isDiscovering} onClick={onFindProspects}>
              {isDiscovering ? "Finding prospects" : "Find prospects"}
            </Button>
            <Button icon={Plus} onClick={() => setShowForm((v) => !v)}>
              {showForm ? "Cancel" : "Add prospect"}
            </Button>
          </>
        }
      />

      {campaign?.discovery_status && DISCOVERY_MESSAGES[campaign.discovery_status] && (
        <div className="mb-6 text-sm text-muted-foreground">{DISCOVERY_MESSAGES[campaign.discovery_status]}</div>
      )}

      {showForm && (
        <div className="mb-6">
          <NewProspectForm
            campaignId={id}
            onCreated={() => {
              setShowForm(false);
              refresh();
            }}
          />
        </div>
      )}

      {discoveredCandidates.length > 0 && (
        <div className="mb-8">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">
            Needs your review ({discoveredCandidates.length})
          </h2>
          <div className="flex flex-col gap-2">
            {discoveredCandidates.map((p) => (
              <DiscoveredCandidateCard
                key={p.id}
                prospect={p}
                onStarted={refresh}
                onDismissed={() => onDismissCandidate(p.id, p.name)}
              />
            ))}
          </div>
        </div>
      )}

      {loading ? (
        <LoadingState />
      ) : pipelineProspects.length === 0 && discoveredCandidates.length === 0 ? (
        <EmptyState
          icon={Users}
          title="No prospects yet"
          description='Click "Find prospects" to have the AI search for candidates, or add one manually.'
          action={
            !showForm && (
              <Button size="sm" icon={Plus} onClick={() => setShowForm(true)}>
                Add prospect
              </Button>
            )
          }
        />
      ) : pipelineProspects.length > 0 ? (
        <div className="flex flex-col gap-2">
          {pipelineProspects.map((p) => (
            <Card key={p.id} className="px-5 py-4 group">
              <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="font-medium truncate">
                    {p.name} <span className="text-muted-foreground font-normal">— {p.title || "unknown title"} @ {p.company}</span>
                  </div>
                  <div className="text-sm text-muted-foreground">{p.email}</div>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  {p.icp_score !== null && (
                    <span className="text-sm text-muted-foreground tabular-nums">ICP {p.icp_score}/10</span>
                  )}
                  <StatusBadge status={p.status} />
                  <button
                    onClick={() => onDeleteProspect(p.id, p.name)}
                    aria-label={`Delete ${p.name}`}
                    className="p-1 rounded-md text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-danger hover:bg-danger-bg transition-colors"
                  >
                    <Trash2 className="size-4" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function DiscoveredCandidateCard({
  prospect,
  onStarted,
  onDismissed,
}: {
  prospect: Prospect;
  onStarted: () => void;
  onDismissed: () => void;
}) {
  const [email, setEmail] = useState(prospect.email ?? "");
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    try {
      await startOutreach(prospect.id, {
        name: prospect.name,
        title: prospect.title,
        company: prospect.company,
        email,
        context: prospect.context,
      });
      onStarted();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="px-5 py-4">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="font-medium truncate">
            {prospect.name} <span className="text-muted-foreground font-normal">— {prospect.title || "unknown title"} @ {prospect.company}</span>
          </div>
          {prospect.context && <div className="text-sm text-muted-foreground mt-0.5">{prospect.context}</div>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Input
            type="email"
            required
            placeholder="Confirm email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-56"
          />
          <Button size="sm" onClick={start} loading={busy} disabled={!email}>
            Start outreach
          </Button>
          <button
            onClick={onDismissed}
            aria-label={`Dismiss ${prospect.name}`}
            className="p-1 rounded-md text-muted-foreground hover:text-danger hover:bg-danger-bg transition-colors"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      </div>
    </Card>
  );
}

// Grows a textarea to fit its content instead of letting long text scroll out of
// view horizontally (the default for a single-line <input>).
function autoGrow(e: React.FormEvent<HTMLTextAreaElement>) {
  const el = e.currentTarget;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
}

function NewProspectForm({ campaignId, onCreated }: { campaignId: string; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await createProspect(campaignId, {
        name,
        title: title || null,
        company,
        email,
        context: context || null,
      });
      setName("");
      setTitle("");
      setCompany("");
      setEmail("");
      setContext("");
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4">
          <Field label="Full name">
            <Textarea required rows={1} className="overflow-hidden" onInput={autoGrow} placeholder="Priya Sharma" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Title">
            <Textarea rows={1} className="overflow-hidden" onInput={autoGrow} placeholder="VP of Engineering" value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Company">
            <Textarea required rows={1} className="overflow-hidden" onInput={autoGrow} placeholder="Meridian Tech Solutions" value={company} onChange={(e) => setCompany(e.target.value)} />
          </Field>
          <Field label="Prospect email">
            <Textarea required rows={1} className="overflow-hidden" onInput={autoGrow} placeholder="priya.sharma@meridiantech.in" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
        </div>
        <Field label="Context">
          <Textarea
            placeholder="LinkedIn URL, how you found this lead, anything you already know"
            value={context}
            onChange={(e) => setContext(e.target.value)}
            rows={2}
          />
        </Field>
        <Button type="submit" loading={busy} className="self-start">
          {busy ? "Starting research" : "Add & start research"}
        </Button>
      </form>
    </Card>
  );
}
