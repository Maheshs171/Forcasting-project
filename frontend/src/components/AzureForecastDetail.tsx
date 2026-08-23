import { useState } from "react";
import type { MetricForecast, DataFrequency } from "../lib/api";
import GrowthBanner from "./GrowthBanner";
import BigPictureDonuts from "./BigPictureDonuts";
import GrowthTable from "./GrowthTable";
import TrendChart from "./TrendChart";
import YearOverYearChart from "./YearOverYearChart";
import { MonthlyDetailTable } from "./ForecastDetail";
import ModelSelector from "./ModelSelector";
import ModelCompareTable from "./ModelCompareTable";
import ModelOverlayChart from "./ModelOverlayChart";
import BacktestTable from "./BacktestTable";

const ACCENT_COLOR: Record<string, string> = {
  patients: "#4f46e5",
  encounters: "#0891b2",
  collections: "#059669",
  contact_lenses: "#7c3aed",
};

const PERIOD_WORD: Record<DataFrequency, string> = { month: "month", week: "week", day: "day" };
const YOY_CAPTION: Record<DataFrequency, string> = {
  month: "Year-over-year — same calendar month across every year",
  week: "Year-over-year — same ISO week-of-year across every year",
  day: "Year-over-year — same day-of-year across every year",
};

export default function AzureForecastDetail({ metric, data, isMoney }: { metric: string; data: MetricForecast; isMoney: boolean }) {
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [showOverlay, setShowOverlay] = useState(false);
  const freq: DataFrequency = data.frequency ?? "month";
  const periodWord = PERIOD_WORD[freq];

  const activeKey = selectedModel && data.models[selectedModel] ? selectedModel : data.best_model;
  const active = data.models[activeKey];
  if (!active) return null;

  // Overlay the selected model's fields on top of the base payload so the
  // shared single-model components (GrowthBanner, BigPictureDonuts, etc.)
  // work unmodified regardless of which Azure trial is being viewed.
  const viewData: MetricForecast = {
    ...data,
    model_used: active.model_key,
    next_month: active.next_month,
    by_end_of_year: active.by_end_of_year,
    next_12_months: active.next_12_months,
    growth: active.growth,
    full_forecast: active.full_forecast,
  };

  const multiModel = Object.keys(data.models).length > 1;

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-[11.5px] text-amber-700 dark:text-amber-400">
        Forecasted by Azure AutoML's top trials — Azure wasn't configured for quantile forecasting, so the shaded confidence
        band is a ±15% approximation, not a statistically fitted interval (the local dashboard's bands are fitted; this one
        isn't). Accuracy and MAPE come from Azure's own cross-validation, an overall figure rather than the near/long-term
        split the local pipeline computes.
      </div>

      {multiModel && <ModelSelector models={data.models} selected={activeKey} onSelect={setSelectedModel} />}

      <GrowthBanner mtdPct={viewData.growth?.mtd_growth_pct} ytdPct={viewData.growth?.ytd_growth_pct} />

      <BigPictureDonuts data={viewData} isMoney={isMoney} periodWord={periodWord} />

      <GrowthTable data={viewData} isMoney={isMoney} />

      <div className="glass rounded-2xl p-6">
        <div className="flex items-center justify-between mb-3">
          <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium">
            {showOverlay ? "All Azure trials overlaid" : `Historical + Azure forecast trend — ${active.model_name}`}
          </div>
          {multiModel && (
            <button
              onClick={() => setShowOverlay((s) => !s)}
              className="text-[11.5px] font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300"
            >
              {showOverlay ? "Show single model" : "Compare all trials on one chart"}
            </button>
          )}
        </div>
        {showOverlay ? (
          <ModelOverlayChart models={data.models} isMoney={isMoney} height={320} />
        ) : (
          <TrendChart points={viewData.full_forecast} history={data.history_full} isMoney={isMoney} color={ACCENT_COLOR[metric] ?? "#4f46e5"} height={320} />
        )}
      </div>

      <div className="glass rounded-2xl p-6">
        <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-1">
          {YOY_CAPTION[freq]}
        </div>
        <p className="text-[11.5px] text-slate-400 dark:text-slate-500 mb-3">
          Each line is one year of actual data; the dashed line is Azure's forecast.
        </p>
        <YearOverYearChart yoyHistory={data.yoy_history ?? []} forecast={viewData.full_forecast} isMoney={isMoney} height={300} mode={freq} />
      </div>

      {multiModel && <ModelCompareTable models={data.models} isMoney={isMoney} selected={activeKey} onSelect={setSelectedModel} />}

      <div className="glass rounded-2xl p-6">
        <MonthlyDetailTable points={viewData.full_forecast} isMoney={isMoney} periodWord={periodWord} />
      </div>

      {data.backtest && (
        <div className="glass rounded-2xl p-6">
          <div className="text-[13px] font-semibold text-slate-900 dark:text-slate-100 mb-4">Azure algorithm leaderboard (backtest-equivalent)</div>
          <BacktestTable report={{ metric: data.metric, candidates: data.backtest, best_model: data.best_model }} />
        </div>
      )}
    </div>
  );
}
