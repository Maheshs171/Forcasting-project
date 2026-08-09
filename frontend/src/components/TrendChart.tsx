import {
  ComposedChart,
  Area,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from "recharts";
import type { ForecastPoint, HistoryPoint } from "../lib/api";
import { fmtCompact } from "../lib/format";

interface Props {
  points: ForecastPoint[];
  history?: HistoryPoint[];
  isMoney?: boolean;
  height?: number;
  color?: string;
}

export default function TrendChart({ points, history = [], isMoney = false, height = 300, color = "#4f46e5" }: Props) {
  const historyRows = history.map((p) => ({
    label: p.label,
    actual: p.value,
  }));
  const forecastRows = points.map((p) => ({
    label: p.label,
    predicted: p.predicted,
    low: p.low,
    high: p.high,
  }));
  const data = [...historyRows, ...forecastRows];
  const firstForecastLabel = forecastRows[0]?.label;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.18} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: "var(--chart-tick)", fontSize: 11 }}
          axisLine={{ stroke: "var(--chart-axis-line)" }}
          tickLine={false}
          interval={Math.max(0, Math.floor(data.length / 8))}
        />
        <YAxis
          tick={{ fill: "var(--chart-tick)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => fmtCompact(v, isMoney)}
          width={56}
        />
        <Tooltip
          contentStyle={{
            background: "var(--chart-tooltip-bg)",
            border: "1px solid var(--chart-tooltip-border)",
            borderRadius: 10,
            fontSize: 12,
            boxShadow: "0 8px 24px -8px rgba(15,23,42,0.15)",
          }}
          labelStyle={{ color: "var(--chart-label-fg)", marginBottom: 4, fontWeight: 600 }}
          itemStyle={{ color: "var(--chart-tooltip-fg)" }}
          formatter={(value, name) => {
            const v = typeof value === "number" ? value : Number(value);
            if (name === "high" || name === "low") return [fmtCompact(v, isMoney), String(name)];
            if (name === "actual") return [fmtCompact(v, isMoney), "actual"];
            return [fmtCompact(v, isMoney), "forecast"];
          }}
        />
        <Area type="monotone" dataKey="high" stroke="none" fill="url(#bandFill)" isAnimationActive={false} />
        <Area type="monotone" dataKey="low" stroke="none" fill="var(--chart-surface)" isAnimationActive={false} fillOpacity={1} />
        <Line
          type="monotone"
          dataKey="actual"
          stroke="var(--chart-label-fg)"
          strokeWidth={2}
          dot={{ r: 2, fill: "var(--chart-label-fg)", strokeWidth: 0 }}
          isAnimationActive={false}
          name="actual"
        />
        <Line
          type="monotone"
          dataKey="predicted"
          stroke={color}
          strokeWidth={2.5}
          strokeDasharray={historyRows.length > 0 ? "5 3" : undefined}
          dot={{ r: 3, fill: color, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
          isAnimationActive
          name="forecast"
        />
        {firstForecastLabel && <ReferenceLine x={firstForecastLabel} stroke="var(--chart-axis-line)" strokeDasharray="3 3" label={{ value: "today", position: "insideTopLeft", fill: "var(--chart-tick)", fontSize: 10 }} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
