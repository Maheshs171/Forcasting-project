import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ArrowRight, PlayCircle, RefreshCw, Users, Stethoscope, DollarSign, Contact } from "lucide-react";
import { api, type DataFrequency } from "../lib/api";
import { LoadingSpinner, EmptyState } from "../components/Misc";
import { ModelBadge } from "../components/Badges";
import KpiCard from "../components/KpiCard";
import { fmtNumber } from "../lib/format";
import { motion } from "framer-motion";

const FREQUENCY_LABELS: Record<DataFrequency, string> = { month: "Monthly", week: "Weekly", day: "Daily" };
const PERIOD_WORD: Record<DataFrequency, string> = { month: "month", week: "week", day: "day" };
const FREQUENCY_ADVERB: Record<DataFrequency, string> = { month: "monthly", week: "weekly", day: "daily" };

function FrequencyToggle({ value, onChange }: { value: DataFrequency; onChange: (f: DataFrequency) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-0.5 shadow-sm">
      {(Object.keys(FREQUENCY_LABELS) as DataFrequency[]).map((f) => (
        <button
          key={f}
          onClick={() => onChange(f)}
          className={`rounded-md px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
            value === f ? "bg-indigo-600 text-white shadow-sm" : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          {FREQUENCY_LABELS[f]}
        </button>
      ))}
    </div>
  );
}

const ICONS: Record<string, typeof Users> = {
  patients: Users,
  encounters: Stethoscope,
  collections: DollarSign,
  contact_lenses: Contact,
};

const ACCENT: Record<string, string> = {
  patients: "#4f46e5",
  encounters: "#0891b2",
  collections: "#059669",
  contact_lenses: "#7c3aed",
};

const KPI_ACCENT: Record<string, "indigo" | "cyan" | "emerald" | "amber"> = {
  patients: "indigo",
  encounters: "cyan",
  collections: "emerald",
  contact_lenses: "amber",
};

export default function Overview() {
  const { data: metricsMeta } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [frequency, setFrequency] = useState<DataFrequency>("month");
  const periodWord = PERIOD_WORD[frequency];
  const { data: forecasts, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["all-forecasts", frequency],
    queryFn: () => api.allForecasts(frequency),
  });

  const anyData = forecasts && Object.values(forecasts).some((v) => v);

  return (
    <div className="max-w-6xl mx-auto space-y-7">
      <div className="flex items-end justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900 dark:text-slate-100">Business forecast overview</h1>
          <p className="text-[13px] text-slate-400 dark:text-slate-500 mt-1">
            New patients, encounters, collections, and contact lens sales — this {periodWord}, next {periodWord}, and by year-end.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <FrequencyToggle value={frequency} onChange={setFrequency} />
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-[12.5px] text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
          >
            <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
          <Link
            to="/train"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-[12.5px] font-medium text-white hover:bg-indigo-500 transition-colors shadow-md shadow-indigo-200 dark:shadow-indigo-950/50"
          >
            <PlayCircle size={14} />
            Run training pipeline
          </Link>
        </div>
      </div>

      {isLoading && <LoadingSpinner label="Loading latest forecasts…" />}

      {!isLoading && !anyData && (
        <EmptyState
          label={`No ${FREQUENCY_ADVERB[frequency]} forecasts have been generated yet. Head to the Training Pipeline, select "${FREQUENCY_LABELS[frequency]}", and run your first backtest + prediction.`}
          action={
            <Link
              to="/train"
              className="mt-1 inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-[12.5px] font-medium text-white hover:bg-indigo-500 transition-colors"
            >
              <PlayCircle size={14} />
              Go to Training Pipeline
            </Link>
          }
        />
      )}

      {!isLoading && anyData && (
        <>
          {/* KPI hero strip — one glanceable card per metric, sparkline + trend */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {metricsMeta?.map((m, i) => {
              const data = forecasts?.[m.key];
              if (!data) return null;
              const Icon = ICONS[m.key] ?? Users;
              const trend = data.history_full?.slice(-8).map((p) => p.value);
              const trendPct = data.growth?.mtd_growth_pct ?? data.growth?.ytd_growth_pct ?? null;
              return (
                <KpiCard
                  key={m.key}
                  label={m.label}
                  value={fmtNumber(data.by_end_of_year.total_estimate, m.is_money)}
                  sub={`by end of ${data.by_end_of_year.year}`}
                  icon={<Icon size={16} />}
                  accent={KPI_ACCENT[m.key] ?? "indigo"}
                  delay={i * 0.04}
                  trend={trend}
                  trendPct={trendPct}
                />
              );
            })}
          </div>

          {/* Per-metric detail cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {metricsMeta?.map((m, i) => {
              const data = forecasts?.[m.key];
              const Icon = ICONS[m.key] ?? Users;
              const accent = ACCENT[m.key] ?? "#4f46e5";

              if (!data) {
                return (
                  <div key={m.key} className="glass rounded-2xl p-6 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className="h-10 w-10 rounded-xl flex items-center justify-center" style={{ background: `${accent}15` }}>
                        <Icon size={18} style={{ color: accent }} />
                      </div>
                      <div>
                        <div className="text-[15px] font-medium text-slate-700 dark:text-slate-200">{m.label}</div>
                        <div className="text-[12px] text-slate-400 dark:text-slate-500 mt-0.5">No forecast yet</div>
                      </div>
                    </div>
                    <Link to="/train" className="text-[12px] text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium">
                      Run →
                    </Link>
                  </div>
                );
              }

              return (
                <motion.div
                  key={m.key}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: i * 0.05 }}
                >
                  <Link to={`/forecast/${m.key}`} className="block glass rounded-2xl p-6 hover:border-slate-300 dark:hover:border-slate-600 transition-colors group">
                    <div className="flex items-center justify-between mb-4">
                      <div className="flex items-center gap-3">
                        <div className="h-10 w-10 rounded-xl flex items-center justify-center" style={{ background: `${accent}15` }}>
                          <Icon size={18} style={{ color: accent }} />
                        </div>
                        <div>
                          <div className="text-[15px] font-semibold text-slate-900 dark:text-slate-100">{m.label}</div>
                          <div className="flex items-center gap-1.5 mt-1">
                            <ModelBadge model={data.model_used} />
                            {data.models && (
                              <span className="text-[10.5px] text-slate-400 dark:text-slate-500">
                                vs {Object.keys(data.models).length - 1} others
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <ArrowRight size={16} className="text-slate-300 dark:text-slate-600 group-hover:text-slate-500 dark:group-hover:text-slate-300 group-hover:translate-x-0.5 transition-all" />
                    </div>

                    <div className="grid grid-cols-3 gap-3">
                      <div>
                        <div className="text-[10.5px] uppercase tracking-wide text-slate-400 dark:text-slate-500">This {periodWord}</div>
                        <div className="text-[18px] font-semibold text-slate-800 dark:text-slate-100 mono">{fmtNumber(data.this_month.projected_total, m.is_money)}</div>
                      </div>
                      <div>
                        <div className="text-[10.5px] uppercase tracking-wide text-slate-400 dark:text-slate-500">Next {periodWord}</div>
                        <div className="text-[18px] font-semibold text-slate-800 dark:text-slate-100 mono">
                          {data.next_month ? fmtNumber(data.next_month.projected_total, m.is_money) : "—"}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10.5px] uppercase tracking-wide text-slate-400 dark:text-slate-500">By end of {data.by_end_of_year.year}</div>
                        <div className="text-[18px] font-semibold text-slate-800 dark:text-slate-100 mono">{fmtNumber(data.by_end_of_year.total_estimate, m.is_money)}</div>
                      </div>
                    </div>
                  </Link>
                </motion.div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
