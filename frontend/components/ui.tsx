import { Loader2, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";

function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------------- Button

const BUTTON_VARIANTS = {
  primary: "bg-primary text-primary-foreground hover:bg-primary-hover shadow-sm",
  outline: "border border-border bg-card hover:bg-muted text-foreground",
  ghost: "hover:bg-muted text-foreground",
  danger: "border border-danger/30 text-danger hover:bg-danger-bg",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof BUTTON_VARIANTS;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: LucideIcon;
}

export function Button({
  variant = "primary",
  size = "md",
  loading = false,
  icon: Icon,
  disabled,
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-all duration-150 active:scale-[0.97] disabled:opacity-50 disabled:active:scale-100 disabled:cursor-not-allowed",
        size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-sm",
        BUTTON_VARIANTS[variant],
        className
      )}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" /> : Icon ? <Icon className="size-4" /> : null}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------------------ Card

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-xl border border-border bg-card shadow-sm", className)}>
      {children}
    </div>
  );
}

// --------------------------------------------------------------------- form controls

const FIELD_CLASS =
  "w-full rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm placeholder:text-muted-foreground outline-none transition-shadow focus:ring-2 focus:ring-ring/40 focus:border-ring";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(FIELD_CLASS, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(FIELD_CLASS, "resize-none", props.className)} />;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-foreground/80">{label}</span>
      {children}
    </label>
  );
}

// ------------------------------------------------------------------------- PageHeader

export function PageHeader({
  title,
  description,
  back,
  actions,
}: {
  title: string;
  description?: string;
  back?: { href: string; label: string };
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 mb-8">
      <div>
        {back && (
          <a
            href={back.href}
            className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors mb-2"
          >
            &larr; {back.label}
          </a>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="text-sm text-muted-foreground mt-1">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}

// -------------------------------------------------------------------------- EmptyState

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-16 px-6 rounded-xl border border-dashed border-border">
      <div className="size-11 rounded-full bg-muted flex items-center justify-center mb-4">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <p className="font-medium">{title}</p>
      {description && <p className="text-sm text-muted-foreground mt-1 max-w-sm">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ----------------------------------------------------------------------------- Loading

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground py-12 justify-center">
      <Loader2 className="size-4 animate-spin" />
      {label}...
    </div>
  );
}
