import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import type { ModelForecast } from "../lib/api";
import { fmtCompact } from "../lib/format";

const MODEL_HEX: Record<string, string> = {
  sarima: "#7c3aed", ets: "#0891b2", prophet: "#db2777",
  naive: "#64748b", xgboost: "#d97706", sarimax: "#059669", ensemble: "#4f46e5",
};

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
        <CartesianGrid stroke="rgba(15,23,42,0.06)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 11 }}
          axisLine={{ stroke: "rgba(15,23,42,0.1)" }}
          tickLine={false}
          interval={Math.max(0, Math.floor(labels.length / 8))}
        />
        <YAxis
          tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => fmtCompact(v, isMoney)}
          width={56}
        />
        <Tooltip
          contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12 }}
          formatter={(v) => (typeof v === "number" ? fmtCompact(v, isMoney) : v)}
        />
        <Legend
          formatter={(value) => <span className="text-[11.5px] text-slate-600">{entries.find((e) => e.model_key === value)?.model_name ?? value}</span>}
        />
        {entries.map((m) => (
          <Line
            key={m.model_key}
            type="monotone"
            dataKey={m.model_key}
            name={m.model_key}
            stroke={MODEL_HEX[m.model_key] ?? "#94a3b8"}
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
