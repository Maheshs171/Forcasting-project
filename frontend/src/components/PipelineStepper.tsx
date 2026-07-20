import { Check, Loader2, Circle } from "lucide-react";
import type { JobSummary } from "../lib/api";

const STEPS = [
  { key: "fetch", label: "Fetch from database" },
  { key: "preprocess", label: "Preprocess & clean" },
  { key: "train", label: "Train candidate models" },
  { key: "evaluate", label: "Evaluate & select" },
];

/** Derives which pipeline step we're on purely from the existing log stream —
 * no backend changes needed, the log lines already mark each phase. */
function currentStepIndex(logs: string[], status: string): number {
  if (status === "completed") return STEPS.length;
  const joined = logs.join("\n");
  if (/Winner:/.test(joined) && /BACKTEST/.test(joined)) {
    // once at least one metric's evaluation finished, keep showing "evaluate" as active
    // until the whole job completes
  }
  if (/BACKTEST/.test(joined) || /Backtesting candidate models/.test(joined)) return 3;
  if (/excluded|Not enough clean history/.test(joined)) return 2;
  if (/Loading|months \(/.test(joined)) return 1;
  return 0;
}

export default function PipelineStepper({ job }: { job?: JobSummary }) {
  const logs = job?.logs ?? [];
  const status = job?.status ?? "queued";
  const activeIdx = job ? currentStepIndex(logs, status) : -1;

  return (
    <div className="flex items-center justify-between">
      {STEPS.map((step, i) => {
        const done = status === "completed" || i < activeIdx;
        const active = !done && i === activeIdx && status === "running";
        const failed = status === "failed" && i === activeIdx;
        return (
          <div key={step.key} className="flex-1 flex items-center">
            <div className="flex flex-col items-center gap-1.5 flex-1">
              <div
                className={`h-8 w-8 rounded-full flex items-center justify-center border-2 transition-colors ${
                  failed
                    ? "border-red-400 bg-red-50 text-red-500"
                    : done
                    ? "border-emerald-500 bg-emerald-500 text-white"
                    : active
                    ? "border-indigo-500 bg-indigo-50 text-indigo-600"
                    : "border-slate-200 bg-white text-slate-300"
                }`}
              >
                {done ? <Check size={15} /> : active ? <Loader2 size={14} className="animate-spin" /> : <Circle size={8} fill="currentColor" />}
              </div>
              <span className={`text-[11px] text-center font-medium ${done || active ? "text-slate-700" : "text-slate-400"}`}>
                {step.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <div className={`h-0.5 flex-1 -mt-5 ${done ? "bg-emerald-400" : "bg-slate-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}
