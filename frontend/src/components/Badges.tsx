import { prettifyModelKey } from "../lib/modelNames";

const MODEL_COLORS: Record<string, string> = {
  sarima: "bg-violet-50 text-violet-700 border-violet-200",
  ets: "bg-cyan-50 text-cyan-700 border-cyan-200",
  prophet: "bg-rose-50 text-rose-700 border-rose-200",
  naive: "bg-slate-100 text-slate-600 border-slate-200",
  xgboost: "bg-amber-50 text-amber-700 border-amber-200",
  sarimax: "bg-emerald-50 text-emerald-700 border-emerald-200",
  ensemble: "bg-indigo-50 text-indigo-700 border-indigo-200",
  random_forest: "bg-lime-50 text-lime-700 border-lime-200",
  extra_trees: "bg-teal-50 text-teal-700 border-teal-200",
  mlforecast: "bg-orange-50 text-orange-700 border-orange-200",
  autots: "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
};

export function ModelBadge({ model }: { model: string }) {
  const cls = MODEL_COLORS[model] ?? "bg-slate-100 text-slate-600 border-slate-200";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${cls}`}>
      {prettifyModelKey(model)}
    </span>
  );
}

export function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    queued: "bg-slate-100 text-slate-600 border-slate-200",
    running: "bg-indigo-50 text-indigo-700 border-indigo-200",
    completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
    failed: "bg-red-50 text-red-700 border-red-200",
  };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${map[status] ?? map.queued}`}>
      {status === "running" && <span className="h-1.5 w-1.5 rounded-full bg-indigo-500 pulse-dot" />}
      {status}
    </span>
  );
}
