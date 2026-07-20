import { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, ExternalLink, RefreshCw, PlayCircle, LayoutGrid } from "lucide-react";
import { api, type MetricKey, type MetricForecast } from "../lib/api";
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
import { timeAgo } from "../lib/format";

const ACCENT_COLOR: Record<string, string> = {
  patients: "#4f46e5",
  encounters: "#0891b2",
  collections: "#059669",
  contact_lenses: "#7c3aed",
};

export default function MetricDashboard() {
  const { metric } = useParams<{ metric: string }>();
  const key = metric as MetricKey;

  const { data: metricsMeta } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const meta = metricsMeta?.find((m) => m.key === key);

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ["forecast", key],
    queryFn: () => api.forecast(key),
    enabled: !!key,
    retry: false,
  });

  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [showOverlay, setShowOverlay] = useState(false);

  useEffect(() => {
    setSelectedModel(null);
  }, [key]);

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
          <Link to="/" className="inline-flex items-center gap-1 text-[12px] text-slate-400 hover:text-slate-600 mb-1.5">
            <ArrowLeft size={13} /> All forecasts
          </Link>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900">
            {meta?.label ?? "Forecast"}
          </h1>
          {data && active && (
            <div className="flex items-center gap-2 mt-1 flex-wrap">
              <ModelBadge model={active.model_key} />
              {!active.is_recommended && (
                <span className="text-[10.5px] font-medium text-indigo-600 bg-indigo-50 rounded-full px-2 py-0.5">
                  viewing (recommended: {data.models[data.best_model]?.model_name})
                </span>
              )}
              <span className="text-[11.5px] text-slate-400">
                {data.history_months} months of history &middot; {data.horizon_months} months forecast &middot; generated {timeAgo(data._generated_at)}
              </span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => refetch()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12.5px] text-slate-500 hover:text-slate-900 hover:bg-slate-50 transition-colors"
          >
            <RefreshCw size={13} className={isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
          {data?._chart_url && (
            <a
              href={data._chart_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-[12.5px] text-slate-500 hover:text-slate-900 hover:bg-slate-50 transition-colors"
            >
              <ExternalLink size={13} /> Standalone chart
            </a>
          )}
          <Link
            to="/train"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-[12.5px] font-medium text-white hover:bg-indigo-500 transition-colors shadow-md shadow-indigo-200"
          >
            <PlayCircle size={14} />
            Retrain
          </Link>
        </div>
      </div>

      {isLoading && <MetricPageSkeleton />}

      {!isLoading && (error || !data) && (
        <EmptyState
          label={`No forecast yet for ${meta?.label ?? "this metric"}. Run the training pipeline to generate one.`}
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

              <BigPictureDonuts data={viewData} isMoney={meta?.is_money ?? false} />

              <GrowthTable data={viewData} isMoney={meta?.is_money ?? false} />

              <div className="glass rounded-2xl p-6">
                <div className="flex items-center justify-between mb-3">
                  <div className="text-[11px] uppercase tracking-wider text-slate-400 font-medium">
                    {showOverlay ? "All models overlaid" : `Historical + forecast trend — ${active.model_name}`}
                  </div>
                  <button
                    onClick={() => setShowOverlay((s) => !s)}
                    className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-indigo-600 hover:text-indigo-700"
                  >
                    <LayoutGrid size={13} />
                    {showOverlay ? "Show single model" : "Compare all models on one chart"}
                  </button>
                </div>
                {showOverlay ? (
                  <ModelOverlayChart models={data.models} isMoney={meta?.is_money ?? false} height={340} />
                ) : (
                  <TrendChart points={viewData.full_forecast} isMoney={meta?.is_money ?? false} color={ACCENT_COLOR[key] ?? "#4f46e5"} height={340} />
                )}
              </div>

              <ModelCompareTable models={data.models} isMoney={meta?.is_money ?? false} selected={activeKey!} onSelect={setSelectedModel} />

              <div className="glass rounded-2xl p-6">
                <MonthlyDetailTable points={viewData.full_forecast} isMoney={meta?.is_money ?? false} />
              </div>
            </motion.div>

          {data.backtest && (
            <div className="glass rounded-2xl p-6">
              <div className="text-[13px] font-semibold text-slate-900 mb-4">Model backtest comparison</div>
              <BacktestTable report={{ metric: data.metric, candidates: data.backtest, best_model: data.best_model }} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
