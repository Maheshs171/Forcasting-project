import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell, LabelList } from "recharts";
import type { BacktestReport } from "../lib/api";
import { prettifyModelKey, modelColor } from "../lib/modelNames";

export default function BacktestBarChart({ report }: { report: BacktestReport }) {
  const data = Object.entries(report.candidates)
    .filter(([, c]) => c.accuracy_pct !== undefined)
    .map(([key, c]) => ({
      key,
      name: prettifyModelKey(key),
      accuracy: Math.round(c.accuracy_pct!),
      isBest: key === report.best_model,
      flat: !!c.flat_forecast_penalty_applied,
    }))
    .sort((a, b) => b.accuracy - a.accuracy);

  if (!data.length) return <div className="text-[12px] text-slate-400 dark:text-slate-500 italic py-6 text-center">No scored candidates</div>;

  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 44)}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
        <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} tick={{ fill: "var(--chart-tick)", fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={(v) => `${v}%`} />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: "var(--chart-label-fg)", fontSize: 12, fontWeight: 500 }}
          axisLine={false}
          tickLine={false}
          width={100}
        />
        <Tooltip
          contentStyle={{ background: "var(--chart-tooltip-bg)", border: "1px solid var(--chart-tooltip-border)", borderRadius: 10, fontSize: 12, color: "var(--chart-tooltip-fg)" }}
          formatter={(v) => [`${v}% accurate`, "Accuracy"]}
        />
        <Bar dataKey="accuracy" radius={[0, 6, 6, 0]} barSize={22}>
          {data.map((d) => (
            <Cell key={d.key} fill={d.isBest ? "#059669" : modelColor(d.key)} fillOpacity={d.isBest ? 1 : 0.5} />
          ))}
          <LabelList dataKey="accuracy" position="right" formatter={(v) => `${v}%`} style={{ fontSize: 11, fill: "var(--chart-label-fg)", fontWeight: 600 }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
