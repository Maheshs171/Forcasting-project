import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { ModelForecast } from "../lib/api";
import { fmtCompact } from "../lib/format";
import { modelColor } from "../lib/modelNames";

export default function ModelOverlayChart({
  models,
  isMoney,
  height = 320,
}: {
  models: Record<string, ModelForecast>;
  isMoney: boolean;
  height?: number;
}) {
  const entries = Object.values(models);
  const labels = entries[0]?.full_forecast.map((p) => p.label) ?? [];

  const data = labels.map((label, i) => {
    const row: Record<string, string | number> = { label };
    for (const m of entries) {
      const point = m.full_forecast[i];
      if (point) row[m.model_key] = Math.round(point.predicted);
    }
    return row;
  });

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: "var(--chart-tick)", fontSize: 11 }}
          axisLine={{ stroke: "var(--chart-axis-line)" }}
          tickLine={false}
          interval={Math.max(0, Math.floor(labels.length / 8))}
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
        <Legend
          formatter={(value) => <span className="text-[11.5px] text-slate-600 dark:text-slate-400">{entries.find((e) => e.model_key === value)?.model_name ?? value}</span>}
        />
        {entries.map((m) => (
          <Line
            key={m.model_key}
            type="monotone"
            dataKey={m.model_key}
            name={m.model_key}
            stroke={modelColor(m.model_key)}
            strokeWidth={m.is_recommended ? 3 : 1.75}
            strokeDasharray={m.is_flat ? "4 3" : undefined}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
