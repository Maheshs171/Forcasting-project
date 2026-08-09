import { AlertTriangle, Loader2, Inbox } from "lucide-react";
import type { ReactNode } from "react";

export function DataQualityNotes({ notes }: { notes: string[] }) {
  if (!notes.length) return null;
  return (
    <div className="rounded-xl border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-4 py-3 space-y-1.5">
      <div className="flex items-center gap-1.5 text-amber-800 dark:text-amber-400 text-[11.5px] font-semibold uppercase tracking-wide">
        <AlertTriangle size={13} />
        Data quality notes
      </div>
      {notes.map((n, i) => (
        <div key={i} className="text-[12.5px] text-amber-700/90 dark:text-amber-300/80 leading-snug pl-[19px]">
          {n}
        </div>
      ))}
    </div>
  );
}

export function LoadingSpinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400 dark:text-slate-500">
      <Loader2 size={22} className="animate-spin" />
      <span className="text-[13px]">{label}</span>
    </div>
  );
}

function Shimmer({ className = "" }: { className?: string }) {
  return <div className={`rounded-lg bg-slate-100 dark:bg-slate-800 relative overflow-hidden ${className}`}>
    <div className="absolute inset-0 -translate-x-full animate-[shimmer_1.6s_infinite] bg-gradient-to-r from-transparent via-white/70 dark:via-white/10 to-transparent" />
  </div>;
}

export function MetricPageSkeleton() {
  return (
    <div className="space-y-6">
      <Shimmer className="h-16" />
      <div className="glass rounded-2xl p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Shimmer className="h-56" />
          <Shimmer className="h-56" />
        </div>
      </div>
      <Shimmer className="h-40 rounded-2xl" />
      <div className="glass rounded-2xl p-6">
        <Shimmer className="h-80" />
      </div>
    </div>
  );
}

export function EmptyState({ label, action }: { label: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-400 dark:text-slate-500 glass rounded-2xl">
      <Inbox size={26} />
      <span className="text-[13px] text-center max-w-xs">{label}</span>
      {action}
    </div>
  );
}
