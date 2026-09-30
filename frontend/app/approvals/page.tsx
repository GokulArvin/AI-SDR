"use client";

import { ChevronRight, Inbox } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, EmptyState, LoadingState, PageHeader } from "@/components/ui";
import { listApprovals } from "@/lib/api";
import type { Prospect } from "@/lib/types";

export default function ApprovalsPage() {
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listApprovals().then((p) => {
      setProspects(p);
      setLoading(false);
    });
  }, []);

  return (
    <div>
      <PageHeader title="Approval inbox" description="Review each AI-drafted email before it sends." />
      {loading ? (
        <LoadingState />
      ) : prospects.length === 0 ? (
        <EmptyState icon={Inbox} title="All caught up" description="Nothing waiting on you right now." />
      ) : (
        <div className="flex flex-col gap-2">
          {prospects.map((p) => (
            <Link key={p.id} href={`/approvals/${p.id}`}>
              <Card className="px-5 py-4 hover:border-primary/40 hover:shadow-md transition-all">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <div className="font-medium truncate">
                      {p.name} <span className="text-muted-foreground font-normal">— {p.title || "unknown title"} @ {p.company}</span>
                    </div>
                    <div className="text-sm text-muted-foreground">
                      {p.followups_sent === 0 ? "Initial outreach" : `Follow-up #${p.followups_sent}`}
                      {p.icp_score !== null && ` · ICP ${p.icp_score}/10`}
                    </div>
                  </div>
                  <ChevronRight className="size-4 text-muted-foreground shrink-0" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
