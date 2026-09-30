"use client";

import { AlertTriangle, CheckCircle2, Mail, Plus, Target, Trash2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Button, Card, Field, Input, LoadingState, PageHeader, Textarea } from "@/components/ui";
import { createICPProfile, deleteICPProfile, getGmailConnectUrl, getGmailStatus, listICPProfiles } from "@/lib/api";
import type { ICPProfile } from "@/lib/types";

// Mirrors the gmail_error codes backend/app/routers/gmail_auth.py's /gmail/callback
// can redirect back with -- keeps exact user-facing wording in one place.
const GMAIL_ERROR_MESSAGES: Record<string, string> = {
  insufficient_scope:
    "Gmail didn't grant all requested permissions — please try connecting again and make sure to check every permission box (Send email, Read email) on Google's screen.",
  invalid_state: 'That connection attempt expired or was already used — please click "Connect Gmail" again to start fresh.',
  google_api_error: "Google reported an error while finishing the connection — please try connecting again.",
  unknown: "Something went wrong connecting Gmail. Please try again.",
};

function SettingsContent() {
  const searchParams = useSearchParams();
  const justConnected = searchParams.get("gmail_connected");
  const gmailError = searchParams.get("gmail_error");

  const [gmail, setGmail] = useState<{ connected: boolean; email_address: string | null } | null>(null);
  const [icpProfiles, setIcpProfiles] = useState<ICPProfile[]>([]);
  const [showIcpForm, setShowIcpForm] = useState(false);

  const refresh = () => {
    getGmailStatus().then(setGmail);
    listICPProfiles().then(setIcpProfiles);
  };

  useEffect(refresh, []);

  const onDeleteIcp = async (id: string, name: string) => {
    if (!confirm(`Delete ICP profile "${name}"? Campaigns using it will fall back to scoring leads as a generic B2B fit.`)) return;
    await deleteICPProfile(id);
    refresh();
  };

  const connectGmail = async () => {
    const { authorization_url } = await getGmailConnectUrl();
    window.location.href = authorization_url;
  };

  return (
    <div className="flex flex-col gap-10">
      <div>
        <PageHeader title="Settings" description="Connect Gmail and define who counts as a good-fit lead." />
      </div>

      <section>
        <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">Gmail</h2>
        {justConnected && (
          <div className="mb-3 flex items-center gap-2 text-sm text-success">
            <CheckCircle2 className="size-4" /> Connected {justConnected}.
          </div>
        )}
        {gmailError && (
          <div className="mb-3 flex items-center gap-2 rounded-md px-3 py-2 text-sm text-danger bg-danger-bg">
            <AlertTriangle className="size-4 shrink-0" />
            {GMAIL_ERROR_MESSAGES[gmailError] ?? GMAIL_ERROR_MESSAGES.unknown}
          </div>
        )}
        {gmail === null ? (
          <LoadingState />
        ) : (
          <Card className="p-5 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="size-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center">
                <Mail className="size-5" />
              </div>
              {gmail.connected ? (
                <div>
                  <div className="font-medium">{gmail.email_address}</div>
                  <div className="text-sm text-success">Connected</div>
                </div>
              ) : (
                <div>
                  <div className="font-medium">No account connected</div>
                  <div className="text-sm text-muted-foreground">Outreach sends from your own Gmail — no separate email service needed.</div>
                </div>
              )}
            </div>
            <Button variant={gmail.connected ? "outline" : "primary"} size="sm" onClick={connectGmail}>
              {gmail.connected ? "Reconnect" : "Connect Gmail"}
            </Button>
          </Card>
        )}
      </section>

      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">ICP profiles</h2>
          <Button variant="outline" size="sm" icon={Plus} onClick={() => setShowIcpForm((v) => !v)}>
            {showIcpForm ? "Cancel" : "New profile"}
          </Button>
        </div>

        {showIcpForm && (
          <div className="mb-4">
            <NewICPForm
              onCreated={() => {
                setShowIcpForm(false);
                refresh();
              }}
            />
          </div>
        )}

        {icpProfiles.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No ICP profiles yet — campaigns without one score every lead as a generic B2B fit.
          </p>
        ) : (
          <div className="flex flex-col gap-2">
            {icpProfiles.map((icp) => (
              <Card key={icp.id} className="px-5 py-4 flex items-start gap-3 group">
                <Target className="size-4 text-primary mt-0.5 shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium">{icp.name}</div>
                  <div className="text-sm text-muted-foreground">{icp.criteria}</div>
                </div>
                <button
                  onClick={() => onDeleteIcp(icp.id, icp.name)}
                  aria-label={`Delete ${icp.name}`}
                  className="p-1 rounded-md text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-danger hover:bg-danger-bg transition-colors shrink-0"
                >
                  <Trash2 className="size-4" />
                </button>
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function NewICPForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [criteria, setCriteria] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await createICPProfile({ name, criteria });
      onCreated();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <Field label="Profile name">
          <Input required placeholder="e.g. Mid-market SaaS" value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Criteria">
          <Textarea
            required
            placeholder="Describe the ideal customer: company size, industry, buyer role, signals to look for..."
            value={criteria}
            onChange={(e) => setCriteria(e.target.value)}
            rows={3}
          />
        </Field>
        <Button type="submit" loading={busy} className="self-start">
          Save profile
        </Button>
      </form>
    </Card>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<LoadingState />}>
      <SettingsContent />
    </Suspense>
  );
}
