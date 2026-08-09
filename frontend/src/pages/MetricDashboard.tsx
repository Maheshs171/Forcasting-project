import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, ExternalLink, RefreshCw, PlayCircle, LayoutGrid } from "lucide-react";
import { api, type MetricKey, type MetricForecast, type DataFrequency } from "../lib/api";
import { MetricPageSkeleton, EmptyState, DataQualityNotes } from "../components/Misc";
import { ModelBadge } from "../components/Badges";
import GrowthBanner from "../components/GrowthBanner";
import BigPictureDonuts from "../components/BigPictureDonuts";
import GrowthTable from "../components/GrowthTable";
import TrendChart from "../components/TrendChart";
import BacktestTable from "../components/BacktestTable";
import { MonthlyDetailTable } from "../components/ForecastDetail";
import ModelSelector from "../components/ModelSelector";
import ModelCompareTable from "../components/ModelCompareTable";
import ModelOverlayChart from "../components/ModelOverlayChart";
import YearOverYearChart from "../components/YearOverYearChart";
import { timeAgo } from "../lib/format";

const ACCENT_COLOR: Record<string, string> = {
  patients: "#4f46e5",
  encounters: "#0891b2",
  collections: "#059669",
  contact_lenses: "#7c3aed",
};

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

export default function MetricDashboard() {
  const { metric } = useParams<{ metric: string }>();
  const key = metric as MetricKey;

  const { data: metricsMeta } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const meta = metricsMeta?.find((m) => m.key === key);

  const [frequency, setFrequency] = useState<DataFrequency>("month");
  const periodWord = PERIOD_WORD[frequency];

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["forecast", key, frequency],
    queryFn: () => api.forecast(key, frequency),
    enabled: !!key,
    retry: false,
  });

  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [showOverlay, setShowOverlay] = useState(false);

  useEffect(() => {
    setSelectedModel(null);
  }, [key, frequency]);

  const activeKey = selectedModel && data?.models[selectedModel] ? selectedModel : data?.best_model;
  const active = data && activeKey ? data.models[activeKey] : null;

  // Overlay the selected model's fields on top of the base payload so the
  // existing single-model components (GrowthBanner, BigPictureDonuts, etc.)
  // work unmodified regardless of which model is being viewed.
  const viewData: MetricForecast | undefined =
    data && active
      ? {
          ...data,
          model_used: active.model_key,
          next_month: active.next_month,
          by_end_of_year: active.by_end_of_year,
          next_12_months: active.next_12_months,
          growth: active.growth,
          full_forecast: active.full_forecast,
        }
      : data;

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <Link to="/" className="inline-flex items-center gap-1 text-[12px] text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 mb-1.5">
            <ArrowLeft size={13} /> All forecasts
          </Link>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900 dark:text-slate-100">
            {meta?.label ?? "Forecast"}
          </h1>
          {data && active && (
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <ModelBadge model={active.model_key} />
              {!active.is_recommended && (
                <span className="text-[10.5px] font-medium text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 rounded-full px-2 py-0.5">
                  viewing (recommended: {data.models[data.best_model]?.model_name})
                </span>
              )}
              <span className="text-[11.5px] text-slate-400 dark:text-slate-500">
                {data.history_months} {periodWord}s of history &middot; {data.horizon_months} {periodWord}s forecast &middot; generated {timeAgo(data._generated_at)}
              </span>
            </div>
          )}
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
          {data?._chart_url && (
            <a
              href={data._chart_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2 text-[12.5px] text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-100 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <ExternalLink size={13} /> Standalone chart
            </a>
          )}
          <Link
            to="/train"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-[12.5px] font-medium text-white hover:bg-indigo-500 transition-colors shadow-md shadow-indigo-200 dark:shadow-indigo-950/50"
          >
            <PlayCircle size={14} />
            Retrain
          </Link>
        </div>
      </div>

      {isLoading && <MetricPageSkeleton />}

      {!isLoading && (error || !data) && (
        <EmptyState
          label={`No ${FREQUENCY_ADVERB[frequency]} forecast yet for ${meta?.label ?? "this metric"}. Run the training pipeline with "${FREQUENCY_LABELS[frequency]}" selected to generate one.`}
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

      {!isLoading && data && viewData && active && (
        <div className="space-y-6">
          <DataQualityNotes notes={data.data_quality_notes} />

          <ModelSelector models={data.models} selected={activeKey!} onSelect={setSelectedModel} />

          <motion.div
            key={activeKey}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.2 }}
            className="space-y-6"
          >
              <GrowthBanner mtdPct={viewData.growth?.mtd_growth_pct} ytdPct={viewData.growth?.ytd_growth_pct} />

              <BigPictureDonuts data={viewData} isMoney={meta?.is_money ?? false} periodWord={periodWord} />

              <GrowthTable data={viewData} isMoney={meta?.is_money ?? false} />

              <div className="glass rounded-2xl p-6">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium">
                    {showOverlay ? "All models overlaid" : `Historical + forecast trend — ${active.model_name}`}
                  </div>
                  <button
                    onClick={() => setShowOverlay((s) => !s)}
                    className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
                  >
                    <LayoutGrid size={13} />
                    {showOverlay ? "Show single model" : "Compare all models on one chart"}
                  </button>
                </div>
                {showOverlay ? (
                  <ModelOverlayChart models={data.models} isMoney={meta?.is_money ?? false} height={340} />
                ) : (
                  <TrendChart points={viewData.full_forecast} history={data.history_full} isMoney={meta?.is_money ?? false} color={ACCENT_COLOR[key] ?? "#4f46e5"} height={340} />
                )}
              </div>

              <div className="glass rounded-2xl p-6">
                <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-1">
                  {frequency === "week" && "Year-over-year — same ISO week-of-year across every year"}
                  {frequency === "day" && "Year-over-year — same day-of-year across every year"}
                  {frequency === "month" && "Year-over-year — same calendar month across every year"}
                </div>
                <p className="text-[11.5px] text-slate-400 dark:text-slate-500 mb-3">
                  {frequency === "week" &&
                    "Each line is one year of actual data; the dashed line is the forecast — lines that land close together mean that week-of-year behaves consistently year to year."}
                  {frequency === "day" &&
                    "Each line is one year of actual data; the dashed line is the forecast — lines that land close together mean that day-of-year behaves consistently year to year. Dense at this resolution — zoom via the tooltip or compare a shorter date range in Data Explorer for detail."}
                  {frequency === "month" &&
                    "Each line is one year of actual data; the dashed line is the next 12 months forecast — lines that land close together mean that calendar month behaves consistently year to year."}
                </p>
                <YearOverYearChart
                  yoyHistory={data.yoy_history ?? []}
                  forecast={viewData.full_forecast}
                  isMoney={meta?.is_money ?? false}
                  height={320}
                  mode={frequency}
                />
              </div>

              <ModelCompareTable models={data.models} isMoney={meta?.is_money ?? false} selected={activeKey!} onSelect={setSelectedModel} />

              <div className="glass rounded-2xl p-6">
                <MonthlyDetailTable points={viewData.full_forecast} isMoney={meta?.is_money ?? false} periodWord={periodWord} />
              </div>
            </motion.div>

          {data.backtest && (
            <div className="glass rounded-2xl p-6">
              <div className="text-[13px] font-semibold text-slate-900 dark:text-slate-100 mb-4">Model backtest comparison</div>
              <BacktestTable report={{ metric: data.metric, candidates: data.backtest, best_model: data.best_model }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
