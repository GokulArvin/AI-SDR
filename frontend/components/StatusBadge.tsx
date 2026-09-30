import type { ProspectStatus } from "@/lib/types";

const STYLES: Record<string, string> = {
  discovered: "text-warning bg-warning-bg",
  researching: "text-info bg-info-bg",
  pending_approval: "text-warning bg-warning-bg",
  sending: "text-info bg-info-bg",
  awaiting_reply: "text-primary bg-primary/10",
  replied: "text-success bg-success-bg",
  completed_no_response: "text-muted-foreground bg-muted",
  stopped_low_fit: "text-danger bg-danger-bg",
  error: "text-danger bg-danger-bg",
};

// Solid-fill equivalent of STYLES above, for stage bars/rails elsewhere that need a
// single fill color per status rather than a text+background pair.
export const STATUS_FILL: Record<string, string> = {
  discovered: "bg-warning",
  researching: "bg-info",
  pending_approval: "bg-warning",
  sending: "bg-info",
  awaiting_reply: "bg-primary",
  replied: "bg-success",
  completed_no_response: "bg-muted-foreground/40",
  stopped_low_fit: "bg-danger",
  error: "bg-danger",
};

export const STAGE_ORDER: string[] = [
  "discovered",
  "researching",
  "sending",
  "pending_approval",
  "awaiting_reply",
  "replied",
  "stopped_low_fit",
  "completed_no_response",
  "error",
];

export function StatusBadge({ status }: { status: ProspectStatus | string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
        STYLES[status] ?? "bg-muted text-muted-foreground"
      }`}
    >
      <span className="size-1.5 rounded-full bg-current" />
      {status.replaceAll("_", " ")}
    </span>
  );
}
