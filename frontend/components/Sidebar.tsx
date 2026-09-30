"use client";

import { Inbox, Megaphone, Settings, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { listApprovals, listCampaigns } from "@/lib/api";

const LINKS = [
  { href: "/dashboard", label: "Campaigns", icon: Megaphone, countKey: "campaigns" as const },
  { href: "/approvals", label: "Approvals", icon: Inbox, countKey: "approvals" as const },
  { href: "/settings", label: "Settings", icon: Settings, countKey: null },
];

export function Sidebar() {
  const pathname = usePathname();
  const [counts, setCounts] = useState<{ campaigns: number; approvals: number } | null>(null);

  useEffect(() => {
    Promise.all([listCampaigns(), listApprovals()]).then(([campaigns, approvals]) => {
      setCounts({ campaigns: campaigns.length, approvals: approvals.length });
    });
  }, [pathname]);

  return (
    <aside className="w-60 shrink-0 flex flex-col h-screen sticky top-0 bg-sidebar-bg border-r border-sidebar-border">
      <div className="flex items-center justify-between gap-2 px-5 h-16 border-b border-sidebar-border">
        <div className="flex items-center gap-2.5">
          <div className="size-7 rounded-lg bg-gradient-to-br from-primary to-primary-hover text-primary-foreground flex items-center justify-center">
            <Sparkles className="size-4" />
          </div>
          <div>
            <div className="font-semibold tracking-tight text-sm leading-tight text-sidebar-text">AI-SDR</div>
            <div className="text-[10px] leading-tight text-sidebar-text-dim">Outbound, on autopilot</div>
          </div>
        </div>
        <ThemeToggle />
      </div>

      <nav className="flex-1 flex flex-col gap-1 p-3">
        {LINKS.map((link) => {
          const active = pathname?.startsWith(link.href);
          const Icon = link.icon;
          const count = link.countKey && counts ? counts[link.countKey] : null;
          return (
            <Link
              key={link.href}
              href={link.href}
              className={
                active
                  ? "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium bg-sidebar-active-bg text-sidebar-active-text"
                  : "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-sidebar-text-dim hover:bg-white/5 hover:text-sidebar-text transition-colors"
              }
            >
              <Icon className="size-4" />
              {link.label}
              {count !== null && (
                <span
                  className={
                    active
                      ? "ml-auto text-[11px] font-mono tabular-nums bg-sidebar-active-text/20 text-sidebar-active-text rounded-full px-1.5 py-0.5"
                      : "ml-auto text-[11px] font-mono tabular-nums bg-white/8 text-sidebar-text-dim rounded-full px-1.5 py-0.5"
                  }
                >
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="p-4 text-xs text-sidebar-text-dim border-t border-sidebar-border">
        AI-powered outreach, end to end.
      </div>
    </aside>
  );
}
