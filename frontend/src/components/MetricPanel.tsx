import { useState } from "react";
import { motion } from "framer-motion";
import { ExternalLink, ChevronDown, TrendingUp, Calendar, CalendarClock } from "lucide-react";
import type { MetricForecast } from "../lib/api";
import { fmtNumber, fmtMonthLabel, timeAgo } from "../lib/format";
import KpiCard from "./KpiCard";
import TrendChart from "./TrendChart";
import { ModelBadge } from "./Badges";
import { DataQualityNotes } from "./Misc";
import BacktestTable from "./BacktestTable";
import { AggregateStatsRow, PacingBlock, MonthlyDetailTable } from "./ForecastDetail";

export default function MetricPanel({ data, isMoney }: { data: MetricForecast; isMoney: boolean }) {
  const [showBacktest, setShowBacktest] = useState(false);

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="glass rounded-2xl p-6 space-y-5"
    >
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-[16px] font-semibold text-slate-900 tracking-tight">{data.label}</h2>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <ModelBadge model={data.model_used} />
            <span className="text-[11px] text-slate-400">
              {data.history_months} months of history &middot; {data.horizon_months} months forecast
            </span>
            <span className="text-[11px] text-slate-400">&middot; generated {timeAgo(data._generated_at)}</span>
          </div>
        </div>
        {data._chart_url && (
          <a
            href={data._chart_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-[11.5px] text-slate-400 hover:text-slate-500 transition-colors"
          >
            Standalone chart file <ExternalLink size={12} />
          </a>
        )}
      </div>

      <DataQualityNotes notes={data.data_quality_notes} />

      <AggregateStatsRow points={data.full_forecast} isMoney={isMoney} />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <KpiCard
          label={`This month · ${fmtMonthLabel(data.this_month.month)}`}
          value={fmtNumber(data.this_month.projected_total, isMoney)}
          sub={`${fmtNumber(data.this_month.month_to_date_actual, isMoney)} actual so far (day ${data.this_month.as_of_day})`}
          range={`${fmtNumber(data.this_month.low, isMoney)} – ${fmtNumber(data.this_month.high, isMoney)}`}
          icon={<Calendar size={15} />}
          accent="cyan"
        />
        <KpiCard
          label={data.next_month ? `Next month · ${fmtMonthLabel(data.next_month.month)}` : "Next month"}
          value={data.next_month ? fmtNumber(data.next_month.projected_total, isMoney) : "—"}
          sub="Model forecast"
          icon={<CalendarClock size={15} />}
          accent="indigo"
          delay={0.05}
        />
        <KpiCard
          label={`By end of ${data.by_end_of_year.year}`}
          value={fmtNumber(data.by_end_of_year.total_estimate, isMoney)}
          sub={`Actual so far: ${fmtNumber(data.by_end_of_year.actual_so_far, isMoney)}`}
          range={`${fmtNumber(data.by_end_of_year.low, isMoney)} – ${fmtNumber(data.by_end_of_year.high, isMoney)}`}
          icon={<TrendingUp size={15} />}
          accent="emerald"
          delay={0.1}
        />
      </div>

      <PacingBlock data={data} isMoney={isMoney} />

      <div>
        <div className="text-[11px] uppercase tracking-wider text-slate-400 font-medium mb-2">
          Historical + forecast trend
        </div>
        <TrendChart points={data.full_forecast} isMoney={isMoney} />
      </div>

      <MonthlyDetailTable points={data.full_forecast} isMoney={isMoney} />

      {data.backtest && (
        <div>
          <button
            onClick={() => setShowBacktest((s) => !s)}
            className="flex items-center gap-1.5 text-[12px] text-slate-500 hover:text-slate-700 transition-colors"
          >
            <ChevronDown size={14} className={`transition-transform ${showBacktest ? "rotate-180" : ""}`} />
            Model backtest comparison
          </button>
          {showBacktest && (
            <div className="mt-3">
              <BacktestTable report={{ metric: data.metric, candidates: data.backtest, best_model: data.model_used }} />
            </div>
          )}
        </div>
      )}
    </motion.section>
  );
}
