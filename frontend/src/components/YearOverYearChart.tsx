import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { YoyHistoryPoint, ForecastPoint } from "../lib/api";
import { fmtCompact } from "../lib/format";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const YEAR_COLORS = ["#cbd5e1", "#94a3b8", "#0891b2", "#4f46e5", "#7c3aed"];
const FORECAST_COLOR = "#059669";

// ISO week number (Thursday-anchored), matching Python's Timestamp.isocalendar()
// used to build yoy_history on the backend for weekly data.
function isoWeekNumber(date: Date): number {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
}

// Day-of-year (1-366), matching pandas' Timestamp.dayofyear used to build
// yoy_history on the backend for daily data.
function dayOfYear(date: Date): number {
  const start = Date.UTC(date.getUTCFullYear(), 0, 1);
  const today = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
  return Math.floor((today - start) / 86400000) + 1;
}

interface Props {
  yoyHistory: YoyHistoryPoint[];
  forecast: ForecastPoint[];
  isMoney?: boolean;
  height?: number;
  maxYears?: number;
  mode?: "month" | "week" | "day";
}

export default function YearOverYearChart({ yoyHistory, forecast, isMoney = false, height = 320, maxYears = 5, mode = "month" }: Props) {
  if (!yoyHistory || yoyHistory.length === 0) {
    return <div className="text-[12px] text-slate-400 italic py-6 text-center">No historical data available for year-over-year comparison</div>;
  }

  const years = Array.from(new Set(yoyHistory.map((p) => p.year))).sort((a, b) => a - b);
  const shownYears = years.slice(-maxYears);

  // In "month" mode, p.month is a calendar month number (1-12). In "week"
  // mode it's an ISO week-of-year number (1-53). In "day" mode it's a
  // day-of-year number (1-366) — same field, different meaning, set by the
  // backend based on which frequency was forecast.
  const byYearPeriod = new Map<string, number>();
  for (const p of yoyHistory) byYearPeriod.set(`${p.year}-${p.month}`, p.value);

  const periodCount = mode === "day" ? 366 : mode === "week" ? 53 : 12;

  const forecastByPeriod = new Map<number, number>();
  if (mode === "day" || mode === "week") {
    // Every forecast point rather than just the first 12 — a year has ~52
    // weeks/365 days so "next 12" would truncate the horizon most
    // weekly/daily forecasts actually cover. Later points for the same
    // period number (from a horizon spanning >1 year) simply overwrite,
    // which only matters well past a year out.
    const toPeriod = mode === "day" ? dayOfYear : isoWeekNumber;
    for (const p of forecast) {
      const d = new Date(p.month);
      if (isNaN(d.getTime())) continue;
      forecastByPeriod.set(toPeriod(d), p.predicted);
    }
  } else {
    // Only the next 12 months — matches "next 12 month from prediction" and
    // avoids two different forecast years both landing on the same calendar
    // month label if the horizon runs longer than a year.
    for (const p of forecast.slice(0, 12)) {
      const monthNum = Number(p.month.split("-")[1]);
      forecastByPeriod.set(monthNum, p.predicted);
    }
  }

  const data = Array.from({ length: periodCount }, (_, i) => {
    const periodNum = i + 1;
    const label = mode === "day" ? `D${periodNum}` : mode === "week" ? `W${periodNum}` : MONTH_NAMES[i];
    const row: Record<string, string | number | null> = { month: label };
    for (const y of shownYears) {
      const v = byYearPeriod.get(`${y}-${periodNum}`);
      row[String(y)] = v !== undefined ? v : null;
    }
    row["forecast"] = forecastByPeriod.get(periodNum) ?? null;
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis
          dataKey="month"
          tick={{ fill: "var(--chart-tick)", fontSize: 11 }}
          axisLine={{ stroke: "var(--chart-axis-line)" }}
          tickLine={false}
          interval={mode === "day" ? 29 : mode === "week" ? 3 : 0}
        />
        <YAxis
          tick={{ fill: "var(--chart-tick)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => fmtCompact(v, isMoney)}
          width={56}
        />
        <Tooltip
          contentStyle={{ background: "var(--chart-tooltip-bg)", border: "1px solid var(--chart-tooltip-border)", borderRadius: 10, fontSize: 12, color: "var(--chart-tooltip-fg)" }}
          formatter={(v) => (typeof v === "number" ? fmtCompact(v, isMoney) : v)}
        />
        <Legend formatter={(value) => <span className="text-[11.5px] text-slate-600 dark:text-slate-400">{value === "forecast" ? (mode === "month" ? "Forecast (next 12mo)" : "Forecast") : value}</span>} />
        {shownYears.map((y, i) => (
          <Line
            key={y}
            type="monotone"
            dataKey={String(y)}
            stroke={YEAR_COLORS[Math.max(0, YEAR_COLORS.length - shownYears.length + i)]}
            strokeWidth={y === shownYears[shownYears.length - 1] ? 2.5 : 1.5}
            dot={mode === "day" ? false : { r: 2.5 }}
            connectNulls
            isAnimationActive={false}
          />
        ))}
        <Line
          type="monotone"
          dataKey="forecast"
          stroke={FORECAST_COLOR}
          strokeWidth={2.5}
          strokeDasharray="5 3"
          dot={mode === "day" ? false : { r: 2.5, fill: FORECAST_COLOR }}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
