import type { BacktestReport } from "../lib/api";
import { fmtPct } from "../lib/format";
import { ModelBadge } from "./Badges";
import { AlertTriangle } from "lucide-react";

export default function BacktestTable({ report }: { report: BacktestReport }) {
  const entries = Object.entries(report.candidates);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-left text-slate-400 text-[11px] uppercase tracking-wider">
            <th className="pb-2.5 font-medium">Model</th>
            <th className="pb-2.5 font-medium text-right">Folds</th>
            <th className="pb-2.5 font-medium text-right">Accuracy</th>
            <th className="pb-2.5 font-medium text-right">Near-term MAPE</th>
            <th className="pb-2.5 font-medium text-right">Long-term MAPE</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, c]) => {
            const isBest = key === report.best_model;
            if (c.skipped) {
              return (
                <tr key={key} className="border-t border-slate-100">
                  <td className="py-2.5"><ModelBadge model={key} /></td>
                  <td colSpan={4} className="py-2.5 text-slate-400 italic text-right">{c.skipped}</td>
                </tr>
              );
            }
            return (
              <tr
                key={key}
                className={`border-t border-slate-100 ${isBest ? "bg-emerald-50" : ""}`}
              >
                <td className="py-2.5">
                  <div className="flex items-center gap-2">
                    <ModelBadge model={key} />
                    {isBest && (
                      <span className="text-[10px] font-bold text-emerald-600 uppercase tracking-wide">
                        selected
                      </span>
                    )}
                    {c.flat_forecast_penalty_applied && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-amber-600" title="This model's forecast was nearly constant every month and was excluded from selection">
                        <AlertTriangle size={11} /> flat forecast excluded
                      </span>
                    )}
                  </div>
                </td>
                <td className="py-2.5 text-right text-slate-500 mono">{c.n_folds}</td>
                <td className={`py-2.5 text-right mono font-semibold ${isBest ? "text-emerald-600" : "text-slate-700"}`}>
                  {c.accuracy_pct !== undefined ? `${Math.round(c.accuracy_pct)}%` : "—"}
                </td>
                <td className="py-2.5 text-right text-slate-500 mono">{fmtPct(c.near_term_mape)}</td>
                <td className="py-2.5 text-right text-slate-500 mono">{fmtPct(c.long_term_mape)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
