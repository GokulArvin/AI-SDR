"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { Card, LoadingState, PageHeader } from "@/components/ui";
import { getCampaignAnalytics } from "@/lib/api";
import type { CampaignAnalytics } from "@/lib/types";

const FUNNEL_ORDER = [
  "researching",
  "pending_approval",
  "sending",
  "awaiting_reply",
  "replied",
  "completed_no_response",
  "stopped_low_fit",
  "error",
];

export default function AnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<CampaignAnalytics | null>(null);

  useEffect(() => {
    getCampaignAnalytics(id).then(setData);
  }, [id]);

  const maxFunnelCount = data ? Math.max(1, ...Object.values(data.funnel)) : 1;

  return (
    <div>
      <PageHeader title="Campaign analytics" back={{ href: `/campaigns/${id}`, label: "Prospects" }} />

      {!data ? (
        <LoadingState />
      ) : (
        <div className="flex flex-col gap-8">
          <div className="grid grid-cols-3 gap-4">
            <Stat label="Emails sent" value={data.emails_sent} />
            <Stat label="Open rate" value={`${(data.open_rate * 100).toFixed(0)}%`} />
            <Stat label="Click rate" value={`${(data.click_rate * 100).toFixed(0)}%`} />
          </div>

          <div>
            <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-3">Funnel</h2>
            <Card className="p-5 flex flex-col gap-3">
              {FUNNEL_ORDER.filter((status) => data.funnel[status]).map((status) => (
                <div key={status} className="flex items-center gap-4">
                  <span className="w-40 shrink-0 text-sm capitalize">{status.replaceAll("_", " ")}</span>
                  <div className="flex-1 h-2.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={`h-full rounded-full ${status === "error" ? "bg-danger" : "bg-primary"}`}
                      style={{ width: `${(data.funnel[status] / maxFunnelCount) * 100}%` }}
                    />
                  </div>
                  <span className="w-8 text-right text-sm font-medium tabular-nums">{data.funnel[status]}</span>
                </div>
              ))}
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <Card className="p-5">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="text-3xl font-semibold tracking-tight mt-1">{value}</div>
    </Card>
  );
}
