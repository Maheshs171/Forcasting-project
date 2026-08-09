import { useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ForecastPoint, MetricForecast } from "../lib/api";
import { fmtNumber } from "../lib/format";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 px-4 py-3">
      <div className="text-[11px] text-slate-400 dark:text-slate-500">{label}</div>
      <div className="text-[19px] font-semibold text-slate-900 dark:text-slate-100 mono mt-0.5">{value}</div>
      {sub && <div className="text-[10.5px] text-slate-400 dark:text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

export function AggregateStatsRow({ points, isMoney }: { points: ForecastPoint[]; isMoney: boolean }) {
  const total = points.reduce((s, p) => s + p.predicted, 0);
  const low = points.reduce((s, p) => s + p.low, 0);
  const high = points.reduce((s, p) => s + p.high, 0);
  const avg = points.length ? total / points.length : 0;

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <Stat label="Total predicted" value={fmtNumber(total, isMoney)} sub={`over ${points.length} months`} />
      <Stat label="Monthly average" value={fmtNumber(avg, isMoney)} sub="predicted avg/month" />
      <Stat label="95% range (total)" value={`${fmtNumber(low, isMoney)} – ${fmtNumber(high, isMoney)}`} />
      <Stat label="Periods" value={String(points.length)} sub="months forecasted" />
    </div>
  );
}

export function PacingBlock({ data, isMoney }: { data: MetricForecast; isMoney: boolean }) {
  const tm = data.this_month;
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-2">
        Current month pacing · day {tm.as_of_day} of month
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Stat label="Month-to-date actual" value={fmtNumber(tm.month_to_date_actual, isMoney)} />
        <Stat label="Projected month total" value={fmtNumber(tm.projected_total, isMoney)} />
        <Stat label="Range" value={`${fmtNumber(tm.low, isMoney)} – ${fmtNumber(tm.high, isMoney)}`} />
        <Stat
          label="Based on"
          value={tm.history_months_used > 0 ? `${tm.history_months_used} mo.` : "linear est."}
          sub={tm.history_months_used > 0 ? "day-of-month history" : "not enough daily history"}
        />
      </div>
    </div>
  );
}

export function MonthlyDetailTable({ points, isMoney, periodWord = "month" }: { points: ForecastPoint[]; isMoney: boolean; periodWord?: string }) {
  const [open, setOpen] = useState(false);
  const periodWordCap = periodWord.charAt(0).toUpperCase() + periodWord.slice(1);
  const periodAdverb = periodWord === "day" ? "Daily" : `${periodWordCap}ly`;
  return (
    <div>
      <button
        onClick={() => setOpen((s) => !s)}
        className="flex items-center gap-1.5 text-[12px] text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 transition-colors"
      >
        <ChevronDown size={14} className={`transition-transform ${open ? "rotate-180" : ""}`} />
        {periodAdverb} forecast detail ({points.length} {periodWord}s)
      </button>
      {open && (
        <div className="mt-3 max-h-72 overflow-y-auto rounded-xl border border-slate-200 dark:border-slate-700">
          <table className="w-full text-[12.5px]">
            <thead className="sticky top-0 bg-white dark:bg-slate-900">
              <tr className="text-left text-slate-400 dark:text-slate-500 text-[10.5px] uppercase tracking-wider">
                <th className="px-3 py-2 font-medium">{periodWordCap}</th>
                <th className="px-3 py-2 font-medium text-right">Predicted</th>
                <th className="px-3 py-2 font-medium text-right">Low (95%)</th>
                <th className="px-3 py-2 font-medium text-right">High (95%)</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.month} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2 text-slate-600 dark:text-slate-400">{p.label}</td>
                  <td className="px-3 py-2 text-right text-slate-800 dark:text-slate-200 font-medium mono">{fmtNumber(p.predicted, isMoney)}</td>
                  <td className="px-3 py-2 text-right text-slate-500 dark:text-slate-400 mono">{fmtNumber(p.low, isMoney)}</td>
                  <td className="px-3 py-2 text-right text-slate-500 dark:text-slate-400 mono">{fmtNumber(p.high, isMoney)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
