import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

export function StatusPill({ status }) {
  const Icon = status.kind === "loading" ? Loader2 : status.kind === "failed" ? AlertCircle : CheckCircle2;
  return (
    <div className={`image-status ${status.kind}`} role="status" aria-live="polite">
      <Icon size={17} />
      <span>{status.message}</span>
    </div>
  );
}
