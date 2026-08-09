import { AlertTriangle, Star } from "lucide-react";
import type { ModelForecast } from "../lib/api";
import { fmtNumber } from "../lib/format";

export default function ModelCompareTable({
  models,
  isMoney,
  selected,
  onSelect,
}: {
  models: Record<string, ModelForecast>;
  isMoney: boolean;
  selected: string;
  onSelect: (key: string) => void;
}) {
  const entries = Object.values(models).sort((a, b) => (b.accuracy_pct ?? 0) - (a.accuracy_pct ?? 0));

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="bg-[#1e2a5e] text-white text-[13px] font-semibold uppercase tracking-wide px-5 py-3">
        Side-by-side: every model's prediction
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="text-left text-slate-400 dark:text-slate-500 text-[11px] uppercase tracking-wider border-b border-slate-100 dark:border-slate-800">
              <th className="px-5 py-3 font-medium">Model</th>
              <th className="px-4 py-3 font-medium text-right">Accuracy</th>
              <th className="px-4 py-3 font-medium text-right">Next Month</th>
              <th className="px-4 py-3 font-medium text-right">By End of Year</th>
              <th className="px-4 py-3 font-medium text-right">Next 12 Months</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((m) => {
              const isActive = m.model_key === selected;
              return (
                <tr
                  key={m.model_key}
                  onClick={() => onSelect(m.model_key)}
                  className={`border-b border-slate-50 dark:border-slate-800/60 last:border-0 cursor-pointer transition-colors ${
                    isActive ? "bg-indigo-50 dark:bg-indigo-500/10" : "hover:bg-slate-50 dark:hover:bg-slate-800/60"
                  }`}
                >
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className={`font-medium ${isActive ? "text-indigo-700 dark:text-indigo-400" : "text-slate-700 dark:text-slate-300"}`}>{m.model_name}</span>
                      {m.is_recommended && <Star size={12} className="fill-current text-amber-500" />}
                      {m.is_flat && (
                        <span title="Forecast is nearly flat/constant">
                          <AlertTriangle size={12} className="text-amber-500" />
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-right mono font-semibold text-slate-700 dark:text-slate-300">
                    {m.accuracy_pct !== null ? `${Math.round(m.accuracy_pct)}%` : "—"}
                  </td>
                  <td className="px-4 py-3 text-right mono text-slate-600 dark:text-slate-400">
                    {m.next_month ? fmtNumber(m.next_month.projected_total, isMoney) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right mono text-slate-600 dark:text-slate-400">
                    {fmtNumber(m.by_end_of_year.total_estimate, isMoney)}
                  </td>
                  <td className="px-4 py-3 text-right mono text-slate-600 dark:text-slate-400">
                    {fmtNumber(m.next_12_months.total_estimate, isMoney)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
