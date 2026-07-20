import type { ReactNode } from "react";
import type { MetricForecast } from "../lib/api";
import { fmtNumber } from "../lib/format";

function GrowthRow({
  label, value, comparedTo, pct, color, rightOverride,
}: {
  label: string; value: string; comparedTo: string; pct?: number | null; color: string; rightOverride?: ReactNode;
}) {
  const has = pct !== null && pct !== undefined && !Number.isNaN(pct);
  const positive = has && pct! >= 0;
  return (
    <tr className="border-t border-slate-100">
      <td className={`py-3 px-4 font-semibold text-white text-[12.5px]`} style={{ background: color }}>
        {label}
      </td>
      <td className="py-3 px-4 text-[13px] text-slate-700 font-medium">{value}</td>
      <td className="py-3 px-4 text-[12px] text-slate-400">{comparedTo}</td>
      <td className="py-3 px-4 text-right">
        {rightOverride ?? (
          <span className={`inline-flex items-center rounded-md px-2 py-1 text-[12.5px] font-semibold ${
            !has ? "bg-slate-100 text-slate-400" : positive ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
          }`}>
            {has ? `${positive ? "+" : ""}${pct!.toFixed(2)}%` : "n/a"}
          </span>
        )}
      </td>
    </tr>
  );
}

export default function GrowthTable({ data, isMoney }: { data: MetricForecast; isMoney: boolean }) {
  const g = data.growth;
  const n12 = data.next_12_months;
  const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "—" : fmtNumber(v, isMoney));

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="bg-[#1e2a5e] text-white text-[13px] font-semibold uppercase tracking-wide px-5 py-3">
        Your Growth Snapshot
      </div>
      <table className="w-full">
        <tbody>
          <GrowthRow
            label="This Month"
            value={fmt(data.this_month.projected_total)}
            comparedTo={`vs last month: ${fmt(g?.last_month_actual)}`}
            pct={g?.mtd_growth_pct}
            color="#7c3aed"
          />
          {n12 && (
            <GrowthRow
              label="Next 12 Months (rolling)"
              value={fmt(n12.total_estimate)}
              comparedTo={`range: ${fmt(n12.low)} – ${fmt(n12.high)} · ${n12.months_covered} months`}
              color="#4f46e5"
              rightOverride={
                <span className="inline-flex items-center rounded-md px-2 py-1 text-[12.5px] font-semibold bg-indigo-50 text-indigo-700">
                  forecast
                </span>
              }
            />
          )}
          <GrowthRow
            label="Year to Date"
            value={fmt(data.by_end_of_year.actual_so_far + data.this_month.projected_total)}
            comparedTo={`vs same period last year: ${fmt(g?.same_period_last_year_total)}`}
            pct={g?.ytd_growth_pct}
            color="#db2777"
          />
          <GrowthRow
            label={`Full Year ${data.by_end_of_year.year} (projected)`}
            value={fmt(data.by_end_of_year.total_estimate)}
            comparedTo={`vs ${data.by_end_of_year.year - 1} total: ${fmt(g?.last_year_total)}`}
            pct={g?.full_year_growth_pct}
            color="#0891b2"
          />
        </tbody>
      </table>
    </div>
  );
}
