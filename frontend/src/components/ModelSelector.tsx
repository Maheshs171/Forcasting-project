import { AlertTriangle, Star } from "lucide-react";
import type { ModelForecast } from "../lib/api";

const MODEL_COLORS: Record<string, string> = {
  sarima: "border-violet-300 bg-violet-50 text-violet-700",
  ets: "border-cyan-300 bg-cyan-50 text-cyan-700",
  prophet: "border-rose-300 bg-rose-50 text-rose-700",
  naive: "border-slate-300 bg-slate-100 text-slate-600",
  xgboost: "border-amber-300 bg-amber-50 text-amber-700",
  sarimax: "border-emerald-300 bg-emerald-50 text-emerald-700",
  ensemble: "border-indigo-300 bg-indigo-50 text-indigo-700",
};

export default function ModelSelector({
  models,
  selected,
  onSelect,
}: {
  models: Record<string, ModelForecast>;
  selected: string;
  onSelect: (key: string) => void;
}) {
  const entries = Object.values(models).sort((a, b) => (b.accuracy_pct ?? 0) - (a.accuracy_pct ?? 0));

  return (
    <div className="glass rounded-2xl p-4">
      <div className="text-[11px] uppercase tracking-wider text-slate-400 font-medium mb-3 px-1">
        Compare models — pick one to view its full forecast below
      </div>
      <div className="flex flex-wrap gap-2">
        {entries.map((m) => {
          const isActive = m.model_key === selected;
          const colorCls = MODEL_COLORS[m.model_key] ?? "border-slate-300 bg-slate-100 text-slate-600";
          return (
            <button
              key={m.model_key}
              onClick={() => onSelect(m.model_key)}
              className={`flex items-center gap-2 rounded-xl border-2 px-3.5 py-2.5 text-left transition-all ${
                isActive ? colorCls + " shadow-sm" : "border-slate-200 bg-white text-slate-500 hover:border-slate-300"
              }`}
            >
              <div>
                <div className="flex items-center gap-1.5">
                  <span className={`text-[12.5px] font-semibold ${isActive ? "" : "text-slate-700"}`}>{m.model_name}</span>
                  {m.is_recommended && <Star size={12} className="fill-current text-amber-500" />}
                  {m.is_flat && <AlertTriangle size={12} className="text-amber-500" />}
                </div>
                <div className="text-[11px] mt-0.5 opacity-80">
                  {m.accuracy_pct !== null ? `${Math.round(m.accuracy_pct)}% accurate` : "n/a"}
                  {m.is_flat && " · flat forecast"}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
