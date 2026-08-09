import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ComposedChart, Line, Scatter, Bar, BarChart, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from "recharts";
import { Loader2, Microscope, AlertTriangle, TrendingUp, Waves, CalendarX2 } from "lucide-react";
import { api, type DataFrequency } from "../lib/api";
import { fmtNumber, fmtCompact, fmtPct } from "../lib/format";

const FREQUENCY_LABELS: Record<DataFrequency, string> = { month: "Monthly", week: "Weekly", day: "Daily" };
const PERIOD_WORD: Record<DataFrequency, string> = { month: "month", week: "week", day: "day" };
const PERIOD_NOUN_PLURAL: Record<DataFrequency, string> = { month: "Months", week: "Weeks", day: "Days" };
const PERIOD_ABBR: Record<DataFrequency, string> = { month: "mo", week: "wk", day: "d" };
const SEASONAL_CYCLE_LEN: Record<DataFrequency, number> = { month: 12, week: 52, day: 7 };
const SEASONAL_MIN_HISTORY: Record<DataFrequency, string> = {
  month: "24 months (2 years)", week: "104 weeks (2 years)", day: "14 days (2 weeks)",
};
const FREQUENCY_ADVERB: Record<DataFrequency, string> = { month: "monthly", week: "weekly", day: "daily" };

const CHART_TICK = { fill: "var(--chart-tick)", fontSize: 10.5 };
const CHART_GRID = "var(--chart-grid)";
const CHART_AXIS_LINE = { stroke: "var(--chart-axis-line)" };
const TOOLTIP_STYLE = { background: "var(--chart-tooltip-bg)", border: "1px solid var(--chart-tooltip-border)", borderRadius: 10, fontSize: 12, color: "var(--chart-tooltip-fg)" };

function StatCard({ label, value, tone = "slate" }: { label: string; value: string; tone?: "slate" | "amber" | "red" | "emerald" }) {
  const tones: Record<string, string> = {
    slate: "border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 text-slate-900 dark:text-slate-100",
    amber: "border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-400",
    red: "border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400",
    emerald: "border-emerald-200 dark:border-emerald-500/30 bg-emerald-50 dark:bg-emerald-500/10 text-emerald-800 dark:text-emerald-400",
  };
  return (
    <div className={`rounded-xl border px-4 py-3 ${tones[tone]}`}>
      <div className="text-[10.5px] uppercase tracking-wide opacity-70">{label}</div>
      <div className="text-[18px] font-semibold mono mt-0.5">{value}</div>
    </div>
  );
}

function Panel({ title, subtitle, icon: Icon, children }: { title: string; subtitle?: string; icon?: any; children: React.ReactNode }) {
  return (
    <div className="glass rounded-2xl p-6">
      <div className="flex items-center gap-2 mb-1">
        {Icon && <Icon size={15} className="text-slate-400 dark:text-slate-500" />}
        <span className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">{title}</span>
      </div>
      {subtitle && <p className="text-[11.5px] text-slate-400 dark:text-slate-500 mb-4">{subtitle}</p>}
      {!subtitle && <div className="mb-3" />}
      {children}
    </div>
  );
}

export default function DataExplorer() {
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [metric, setMetric] = useState("patients");
  const [frequency, setFrequency] = useState<DataFrequency>("month");
  const isMoney = metrics?.find((m) => m.key === metric)?.is_money ?? false;
  const periodWord = PERIOD_WORD[frequency];

  const { data: report, isLoading, isError } = useQuery({
    queryKey: ["data-insights", metric, frequency],
    queryFn: () => api.dataInsights(metric, undefined, frequency),
  });

  const fmt = (v: number | null | undefined) => fmtCompact(v ?? undefined, isMoney);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2">
            <Microscope size={20} className="text-indigo-500 dark:text-indigo-400" />
            Data Explorer
          </h1>
          <p className="text-[13px] text-slate-400 dark:text-slate-500 mt-1 max-w-2xl">
            The raw numbers behind every forecast — distribution, outliers, gaps, seasonality, and noise —
            pulled live from the database so you can see exactly what the models are learning from before
            trusting their output.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-0.5 shadow-sm">
            {(Object.keys(FREQUENCY_LABELS) as DataFrequency[]).map((f) => (
              <button
                key={f}
                onClick={() => setFrequency(f)}
                className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                  frequency === f ? "bg-indigo-600 text-white shadow-sm" : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
                }`}
              >
                {FREQUENCY_LABELS[f]}
              </button>
            ))}
          </div>
          <select
            className="rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2 text-[13px] font-medium text-slate-700 dark:text-slate-300 shadow-sm"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
          >
            {metrics?.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </div>
      </div>

      {frequency !== "month" && (
        <div className="text-[11.5px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-lg px-3 py-2">
          {periodWord === "day" ? "Daily" : "Weekly"} aggregation is newer than monthly — outlier sensitivity
          hasn't been separately tuned for {periodWord}-level noise yet (it currently reuses the same
          threshold as monthly).
        </div>
      )}

      {isLoading && (
        <div className="glass rounded-2xl p-10 flex items-center justify-center gap-2 text-slate-400 dark:text-slate-500 text-[13px]">
          <Loader2 size={16} className="animate-spin" /> Loading raw data…
        </div>
      )}

      {isError && (
        <div className="glass rounded-2xl p-6 text-[13px] text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30">
          Could not reach the database right now — try again in a moment.
        </div>
      )}

      {report && !report.has_data && (
        <div className="glass rounded-2xl p-6 text-[13px] text-slate-400 dark:text-slate-500 italic text-center">
          No data available for this metric yet.
        </div>
      )}

      {report && report.has_data && (
        <>
          {/* Summary stats */}
          <Panel title="Summary statistics" subtitle="Raw (before cleaning) vs. what the models actually train on (after outlier removal)">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
              <StatCard label={`${PERIOD_NOUN_PLURAL[frequency]} of history`} value={String(report.summary_raw?.n ?? "—")} />
              <StatCard label="Date range" value={report.date_range ? `${report.date_range.start} – ${report.date_range.end}` : "—"} />
              <StatCard label="Mean (raw)" value={fmt(report.summary_raw?.mean)} />
              <StatCard label="Std dev (raw)" value={fmt(report.summary_raw?.std)} />
              <StatCard label="Min / Max (raw)" value={`${fmt(report.summary_raw?.min)} / ${fmt(report.summary_raw?.max)}`} />
              <StatCard
                label="Noise (coefficient of variation)"
                value={report.summary_cleaned?.coefficient_of_variation != null ? fmtPct(report.summary_cleaned.coefficient_of_variation * 100) : "—"}
                tone={((report.summary_cleaned?.coefficient_of_variation ?? 0) > 0.4) ? "amber" : "slate"}
              />
              <StatCard label="Mean (cleaned)" value={fmt(report.summary_cleaned?.mean)} tone="emerald" />
              <StatCard label="Std dev (cleaned)" value={fmt(report.summary_cleaned?.std)} tone="emerald" />
            </div>
            {report.notes.length > 0 && (
              <div className="space-y-1.5 mt-2">
                {report.notes.map((n, i) => (
                  <div key={i} className="text-[12px] text-amber-700 dark:text-amber-400 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-lg px-3 py-1.5">
                    {n}
                  </div>
                ))}
              </div>
            )}
          </Panel>

          {/* Raw series with outliers */}
          <Panel
            title={`Raw ${FREQUENCY_ADVERB[frequency]} values — with outliers highlighted`}
            subtitle={`Each point's robust z-score is checked against a threshold of ${report.outlier_threshold ?? "—"}; anything far outside normal variation (red) is excluded before training`}
            icon={AlertTriangle}
          >
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={report.outliers} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <CartesianGrid stroke={CHART_GRID} vertical={false} />
                <XAxis dataKey="month" tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false}
                  interval={Math.max(0, Math.floor(report.outliers.length / 10))} />
                <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={56} tickFormatter={(v) => fmtCompact(v, isMoney)} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any, name) => [typeof v === "number" ? fmtCompact(v, isMoney) : v, name]} />
                <Line type="monotone" dataKey="value" stroke="#4f46e5" strokeWidth={2} dot={{ r: 2.5, fill: "#4f46e5" }} name="Value" isAnimationActive={false} />
                <Scatter dataKey={(d: any) => (d.excluded ? d.value : null)} fill="#dc2626" name="Excluded outlier" />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          {/* Distribution + Z-score panels side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Panel title={`Distribution of ${FREQUENCY_ADVERB[frequency]} values`} subtitle="How spread out the raw values are">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={report.histogram} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_GRID} vertical={false} />
                  <XAxis
                    dataKey={(d: any) => fmtCompact(d.range_low, isMoney)}
                    tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false}
                  />
                  <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={30} allowDecimals={false} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [`${v} ${periodWord}(s)`, "Count"]} />
                  <Bar dataKey="count" fill="#7c3aed" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel title="Outlier severity (robust z-score)" subtitle="Bars beyond the dashed line are flagged; red = excluded from training" icon={Waves}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={report.outliers} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_GRID} vertical={false} />
                  <XAxis dataKey="month" tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false}
                    interval={Math.max(0, Math.floor(report.outliers.length / 8))} />
                  <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={30} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [Number(v).toFixed(2), "Robust z-score"]} />
                  <ReferenceLine y={report.outlier_threshold ?? 0} stroke="#dc2626" strokeDasharray="4 3" />
                  <ReferenceLine y={-(report.outlier_threshold ?? 0)} stroke="#dc2626" strokeDasharray="4 3" />
                  <Bar dataKey="robust_z_score" radius={[3, 3, 0, 0]}>
                    {report.outliers.map((o, i) => (
                      <Cell key={i} fill={o.excluded ? "#dc2626" : "#94a3b8"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {/* Seasonality + decomposition */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Panel title="Month-of-year seasonality" subtitle="100 = overall average; above 100 means that calendar month typically runs higher" icon={TrendingUp}>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={report.seasonality_index} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_GRID} vertical={false} />
                  <XAxis dataKey="month" tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false} />
                  <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={36} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [Number(v).toFixed(1), "Index"]} />
                  <ReferenceLine y={100} stroke="#94a3b8" strokeDasharray="4 3" />
                  <Bar dataKey="index" radius={[4, 4, 0, 0]}>
                    {report.seasonality_index.map((s, i) => (
                      <Cell key={i} fill={(s.index ?? 100) >= 100 ? "#059669" : "#db2777"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>

            <Panel
              title={`Autocorrelation (lag 1-${report.autocorrelation.length || SEASONAL_CYCLE_LEN[frequency]} ${periodWord}s)`}
              subtitle={`How strongly a ${periodWord}'s value correlates with N ${periodWord}s earlier — high values mean strong repeating patterns`}
            >
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={report.autocorrelation} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_GRID} vertical={false} />
                  <XAxis dataKey="lag" tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false} tickFormatter={(v) => `${v}${PERIOD_ABBR[frequency]}`} />
                  <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={36} domain={[-1, 1]} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [Number(v).toFixed(2), "Correlation"]} />
                  <ReferenceLine y={0} stroke="#94a3b8" />
                  <Bar dataKey="correlation" radius={[3, 3, 0, 0]}>
                    {report.autocorrelation.map((a, i) => (
                      <Cell key={i} fill={Math.abs(a.correlation ?? 0) > 0.5 ? "#4f46e5" : "#cbd5e1"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </div>

          {/* Decomposition */}
          {report.decomposition ? (
            <Panel title="Trend / seasonal / noise breakdown" subtitle="Splits the cleaned series into its three components — this is literally what the statistical models see">
              <div className="grid grid-cols-1 gap-4">
                <MiniSeries label="Trend (long-run direction)" labels={report.decomposition.labels} values={report.decomposition.trend} color="#4f46e5" isMoney={isMoney} />
                <MiniSeries label={`Seasonal (repeating ${frequency === "day" ? "weekly (day-of-week)" : "yearly"} pattern)`} labels={report.decomposition.labels} values={report.decomposition.seasonal} color="#059669" isMoney={isMoney} />
                <MiniSeries label="Residual (unexplained noise)" labels={report.decomposition.labels} values={report.decomposition.residual} color="#db2777" isMoney={isMoney} />
              </div>
            </Panel>
          ) : (
            <Panel title="Trend / seasonal / noise breakdown">
              <div className="text-[12.5px] text-slate-400 dark:text-slate-500 italic text-center py-6">
                Needs at least {SEASONAL_MIN_HISTORY[frequency]} of clean history to
                split trend from seasonality — not enough yet for this metric.
              </div>
            </Panel>
          )}

          {/* Volatility */}
          {report.volatility.length > 0 && (
            <Panel title={`Rolling noise (3-${periodWord} coefficient of variation)`} subtitle="Spikes mean the series got choppier in that stretch — useful for spotting when a metric became less predictable">
              <ResponsiveContainer width="100%" height={200}>
                <ComposedChart data={report.volatility} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid stroke={CHART_GRID} vertical={false} />
                  <XAxis dataKey="month" tick={CHART_TICK} axisLine={CHART_AXIS_LINE} tickLine={false}
                    interval={Math.max(0, Math.floor(report.volatility.length / 10))} />
                  <YAxis tick={CHART_TICK} axisLine={false} tickLine={false} width={40} tickFormatter={(v) => fmtPct(v * 100, 0)} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [fmtPct(Number(v) * 100), "CV"]} />
                  <Line type="monotone" dataKey="coefficient_of_variation" stroke="#f59e0b" strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </Panel>
          )}

          {/* YoY table + gaps */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <Panel title="Year-over-year">
              <div className="overflow-x-auto">
                <table className="w-full text-[12.5px]">
                  <thead>
                    <tr className="text-left text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-800">
                      <th className="py-1.5 font-medium">Year</th>
                      <th className="py-1.5 font-medium">Total</th>
                      <th className="py-1.5 font-medium">Avg/{PERIOD_ABBR[frequency]}</th>
                      <th className="py-1.5 font-medium">{PERIOD_NOUN_PLURAL[frequency]}</th>
                      <th className="py-1.5 font-medium">Growth</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.yoy.map((r) => (
                      <tr key={r.year} className="border-b border-slate-50 dark:border-slate-800/60">
                        <td className="py-1.5 font-medium text-slate-700 dark:text-slate-300">{r.year}</td>
                        <td className="py-1.5 mono dark:text-slate-300">{fmt(r.total)}</td>
                        <td className="py-1.5 mono dark:text-slate-300">{fmt(r.avg_per_month)}</td>
                        <td className="py-1.5 text-slate-400 dark:text-slate-500">{r.months_present}</td>
                        <td className={`py-1.5 mono ${r.growth_pct_vs_prior_year != null && r.growth_pct_vs_prior_year < 0 ? "text-red-600 dark:text-red-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                          {r.growth_pct_vs_prior_year != null ? fmtPct(r.growth_pct_vs_prior_year) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel
              title={`Missing calendar ${periodWord}s`}
              subtitle={`${PERIOD_NOUN_PLURAL[frequency]} inside the data's date range with zero rows at all — a real gap, not just a low value`}
              icon={CalendarX2}
            >
              {report.gaps.length === 0 ? (
                <div className="text-[12.5px] text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-500/30 rounded-lg px-3 py-2">
                  No gaps — every calendar {periodWord} in range has at least one record.
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {report.gaps.map((g) => (
                    <span key={g} className="text-[11.5px] font-medium text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-full px-2.5 py-1">
                      {g}
                    </span>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          {/* Transaction-level (collections only) */}
          {report.transactions && (
            <Panel title="Individual transaction outliers" subtitle="Collections pulls individual payments (no patient identifiers) to catch fake/test entries before they poison a month's total">
              <div className="grid grid-cols-3 gap-3 mb-4">
                <StatCard label="Total transactions" value={fmtNumber(report.transactions.total_count)} />
                <StatCard label="Excluded as outliers" value={fmtNumber(report.transactions.excluded_count)} tone="red" />
                <StatCard label="Excluded $ amount" value={fmtCompact(report.transactions.excluded_total_amount, true)} tone="red" />
              </div>
              {report.transactions.top_excluded.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full text-[12.5px]">
                    <thead>
                      <tr className="text-left text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-800">
                        <th className="py-1.5 font-medium">Date</th>
                        <th className="py-1.5 font-medium">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.transactions.top_excluded.map((t, i) => (
                        <tr key={i} className="border-b border-slate-50 dark:border-slate-800/60">
                          <td className="py-1.5 text-slate-600 dark:text-slate-400">{t.date}</td>
                          <td className="py-1.5 mono text-red-600 dark:text-red-400">{fmtCompact(t.amount, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

function MiniSeries({ label, labels, values, color, isMoney }: { label: string; labels: string[]; values: (number | null)[]; color: string; isMoney: boolean }) {
  const data = labels.map((l, i) => ({ label: l, value: values[i] }));
  return (
    <div>
      <div className="text-[11.5px] font-medium text-slate-500 dark:text-slate-400 mb-1">{label}</div>
      <ResponsiveContainer width="100%" height={110}>
        <ComposedChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid stroke={CHART_GRID} vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 9, fill: "var(--chart-tick)" }} axisLine={false} tickLine={false}
            interval={Math.max(0, Math.floor(data.length / 8))} />
          <YAxis tick={{ fontSize: 9, fill: "var(--chart-tick)" }} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => fmtCompact(v, isMoney)} />
          <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => [typeof v === "number" ? fmtCompact(v, isMoney) : v, label]} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={1.75} dot={false} isAnimationActive={false} connectNulls />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
