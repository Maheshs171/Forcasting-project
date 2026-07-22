import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import type { BacktestReport } from "../lib/api";

const MODEL_HEX: Record<string, string> = {
  sarima: "#7c3aed", ets: "#0891b2", prophet: "#db2777",
  naive: "#64748b", xgboost: "#d97706", sarimax: "#059669", ensemble: "#4f46e5",
};
const MODEL_LABELS: Record<string, string> = {
  sarima: "SARIMA", ets: "ETS", prophet: "Prophet",
  naive: "Seasonal Naive", xgboost: "XGBoost", sarimax: "SARIMAX", ensemble: "Ensemble",
};

export default function BacktestBarChart({ report }: { report: BacktestReport }) {
  const data = Object.entries(report.candidates)
    .filter(([, c]) => c.accuracy_pct !== undefined)
    .map(([key, c]) => ({
      key,
      name: MODEL_LABELS[key] ?? key,
      accuracy: Math.round(c.accuracy_pct!),
      isBest: key === report.best_model,
      flat: !!c.flat_forecast_penalty_applied,
    }))
    .sort((a, b) => b.accuracy - a.accuracy);

  if (!data.length) return <div className="text-[12px] text-slate-400 italic py-6 text-center">No scored candidates</div>;

  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 44)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
        <CartesianGrid stroke="rgba(15,23,42,0.06)" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: "#334155", fontSize: 12, fontWeight: 500 }}
          axisLine={false}
          tickLine={false}
          width={100}
        />
        <Tooltip
          contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12 }}
          formatter={(v) => [`${v}% accurate`, "Accuracy"]}
        />
        <Bar dataKey="accuracy" radius={[0, 6, 6, 0]} barSize={22}>
          {data.map((d) => (
            <Cell key={d.key} fill={d.isBest ? "#059669" : MODEL_HEX[d.key] ?? "#94a3b8"} fillOpacity={d.isBest ? 1 : 0.5} />
          ))}
          <LabelList dataKey="accuracy" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: "#475569", fontWeight: 600 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
