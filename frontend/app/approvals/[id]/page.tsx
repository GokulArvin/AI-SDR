"use client";

import { AlertTriangle, Building2, CheckCircle2, Send, Sparkles, Target, XCircle } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Button, Card, LoadingState, PageHeader, Textarea } from "@/components/ui";
import { getProspect, listProspectEmails, submitApproval } from "@/lib/api";
import type { Email, Prospect } from "@/lib/types";

export default function ApprovalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [prospect, setProspect] = useState<Prospect | null>(null);
  const [draft, setDraft] = useState<Email | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [showReject, setShowReject] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<"approved" | "rejected" | null>(null);

  useEffect(() => {
    Promise.all([getProspect(id), listProspectEmails(id)]).then(([p, emails]) => {
      setProspect(p);
      const current = emails.find((e) => e.step === p.followups_sent) ?? emails[emails.length - 1];
      if (current) {
        setDraft(current);
        setSubject(current.subject);
        setBody(current.body);
      }
    });
  }, [id]);

  const approve = async () => {
    setBusy(true);
    try {
      await submitApproval(id, {
        action: "approve",
        edited_subject: draft && subject !== draft.subject ? subject : null,
        edited_body: draft && body !== draft.body ? body : null,
      });
      setDone("approved");
      setTimeout(() => router.push("/approvals"), 1800);
    } finally {
      setBusy(false);
    }
  };

  const reject = async () => {
    setBusy(true);
    try {
      await submitApproval(id, { action: "reject", rejection_reason: rejectionReason || null });
      setDone("rejected");
      setTimeout(() => router.push("/approvals"), 1800);
    } finally {
      setBusy(false);
    }
  };

  if (!prospect || !draft) return <LoadingState />;

  if (done) {
    return (
      <Card className="p-8 flex flex-col items-center text-center gap-3 max-w-md mx-auto mt-16">
        {done === "approved" ? (
          <CheckCircle2 className="size-10 text-success" />
        ) : (
          <XCircle className="size-10 text-muted-foreground" />
        )}
        <p className="font-medium">
          {done === "approved" ? "Approved — sending via Gmail now" : "Sent back for revision"}
        </p>
        <p className="text-sm text-muted-foreground">
          {done === "approved" ? "The prospect will receive it shortly." : "A new draft will be ready shortly."}
        </p>
      </Card>
    );
  }

  return (
    <div>
      <PageHeader
        title={`${prospect.name} @ ${prospect.company}`}
        back={{ href: "/approvals", label: "Approval inbox" }}
        description={`${prospect.title || "Unknown title"} · ${prospect.email} · ${
          prospect.followups_sent === 0 ? "Initial outreach" : `Follow-up #${prospect.followups_sent}`
        }`}
      />

      <div className="grid grid-cols-1 lg:grid-cols-[1.3fr_1fr] gap-6 items-start">
        <div className="flex flex-col gap-4">
          <Card className="overflow-hidden">
            <div className="px-5 py-3 border-b border-border bg-muted/50 flex items-center gap-2 text-sm text-muted-foreground">
              <Send className="size-3.5" /> Draft email
            </div>
            <div className="p-5 flex flex-col gap-3">
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className="w-full font-medium text-base outline-none bg-transparent border-b border-border pb-3"
              />
              <Textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={12}
                className="border-none px-0 focus:ring-0"
              />
            </div>
          </Card>

          {draft.critic_notes && (
            <Card
              className={`p-4 ${draft.critic_notes.passed ? "border-success/30" : "border-warning/30"}`}
            >
              <div className="flex items-center gap-2 text-sm font-medium mb-1.5">
                {draft.critic_notes.passed ? (
                  <CheckCircle2 className="size-4 text-success" />
                ) : (
                  <AlertTriangle className="size-4 text-warning" />
                )}
                Critic: {draft.critic_notes.passed ? "passed" : "flagged issues"}
              </div>
              {draft.critic_notes.issues.length > 0 && (
                <ul className="list-disc list-inside text-sm text-muted-foreground space-y-0.5 ml-1">
                  {draft.critic_notes.issues.map((issue, i) => (
                    <li key={i}>{issue}</li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <div className="flex gap-2">
            <Button icon={CheckCircle2} onClick={approve} loading={busy}>
              Approve & send
            </Button>
            <Button variant="outline" onClick={() => setShowReject((v) => !v)} disabled={busy}>
              Reject / revise
            </Button>
          </div>

          {showReject && (
            <Card className="p-4 flex flex-col gap-3">
              <Textarea
                placeholder="What should change? (fed back to the drafting agent)"
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                rows={2}
              />
              <Button variant="danger" onClick={reject} loading={busy} className="self-start">
                Send back for revision
              </Button>
            </Card>
          )}
        </div>

        <div className="flex flex-col gap-4">
          {prospect.icp_score !== null && (
            <Card className="p-4">
              <div className="flex items-center gap-2 text-sm font-medium mb-1.5">
                <Target className="size-4 text-primary" />
                ICP fit: {prospect.icp_score}/10
              </div>
              <p className="text-sm text-muted-foreground">{prospect.icp_reasoning}</p>
            </Card>
          )}

          {prospect.research_profile && (
            <Card className="p-4 flex flex-col gap-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-primary" />
                Research
              </div>
              <div className="text-sm">
                <span className="text-muted-foreground">Role: </span>
                {prospect.research_profile.role_summary}
              </div>
              <div className="text-sm flex items-start gap-1.5">
                <Building2 className="size-3.5 text-muted-foreground mt-0.5 shrink-0" />
                <span>
                  <span className="text-muted-foreground">Company: </span>
                  {prospect.research_profile.company_summary}
                </span>
              </div>
              {prospect.research_profile.recent_triggers.length > 0 && (
                <div>
                  <div className="text-muted-foreground text-sm mb-1">Recent triggers</div>
                  <ul className="list-disc list-inside text-sm space-y-0.5 ml-1">
                    {prospect.research_profile.recent_triggers.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
              {prospect.research_profile.likely_pain_points.length > 0 && (
                <div>
                  <div className="text-muted-foreground text-sm mb-1">Likely pain points</div>
                  <ul className="list-disc list-inside text-sm space-y-0.5 ml-1">
                    {prospect.research_profile.likely_pain_points.map((t, i) => (
                      <li key={i}>{t}</li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
