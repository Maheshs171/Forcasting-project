import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from "recharts";
import type { MetricForecast } from "../lib/api";

const YEAR_COLORS = ["#7c3aed", "#db2777", "#0891b2"];
const MODEL_HEX: Record<string, string> = {
  sarima: "#7c3aed",
  ets: "#0891b2",
  prophet: "#db2777",
  naive: "#64748b",
  xgboost: "#d97706",
  sarimax: "#059669",
};
const MODEL_LABELS: Record<string, string> = {
  sarima: "SARIMA", ets: "ETS", prophet: "Prophet", naive: "Seasonal Naive",
  xgboost: "XGBoost", sarimax: "SARIMAX",
};

function DonutCard({ title, data, isMoney }: { title: string; data: { name: string; value: number; color: string }[]; isMoney?: boolean }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  return (
    <div>
      <div className="text-[13px] font-semibold text-slate-700 mb-2 text-center">{title}</div>
      <ResponsiveContainer width="100%" height={230}>
        <PieChart>
          <Pie
            data={data}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={2}
            stroke="#fff"
            strokeWidth={2}
          >
            {data.map((d, i) => (
              <Cell key={i} fill={d.color} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, name) => {
              const v = typeof value === "number" ? value : Number(value);
              return [isMoney ? `$${v.toLocaleString()}` : v.toLocaleString(), String(name)];
            }}
            contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12 }}
          />
          <Legend
            verticalAlign="bottom"
            height={48}
            formatter={(value) => <span className="text-[11.5px] text-slate-600">{value}</span>}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="text-center text-[11px] text-slate-400 -mt-2">
        Total: {isMoney ? `$${total.toLocaleString()}` : total.toLocaleString()}
      </div>
    </div>
  );
}

export default function BigPictureDonuts({ data, isMoney }: { data: MetricForecast; isMoney: boolean }) {
  const yearData = [
    { name: "Actual so far", value: Math.max(data.by_end_of_year.actual_so_far, 0), color: YEAR_COLORS[0] },
    { name: "This month (projected)", value: Math.max(data.by_end_of_year.current_month_estimate, 0), color: YEAR_COLORS[1] },
    { name: "Remaining months (forecast)", value: Math.max(data.by_end_of_year.remaining_months_forecast, 0), color: YEAR_COLORS[2] },
  ].filter((d) => d.value > 0);

  const backtest = data.backtest ?? {};
  const modelData = Object.entries(backtest)
    .filter(([, c]) => c.weighted_score !== undefined && c.weighted_score! > 0)
    .map(([key, c]) => ({
      name: `${MODEL_LABELS[key] ?? key}${key === data.model_used ? " (selected)" : ""}`,
      value: 1 / c.weighted_score!,
      color: MODEL_HEX[key] ?? "#94a3b8",
    }));

  return (
    <div className="glass rounded-2xl p-6">
      <div className="bg-[#1e2a5e] text-white text-[13px] font-semibold uppercase tracking-wide rounded-lg px-4 py-2.5 mb-5 -mt-1">
        The Big Picture
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <DonutCard title={`Your ${data.by_end_of_year.year} Composition`} data={yearData} isMoney={isMoney} />
        {modelData.length > 0 ? (
          <DonutCard title="Model Accuracy Comparison (higher share = more accurate)" data={modelData} />
        ) : (
          <div className="flex items-center justify-center h-full text-[12px] text-slate-400 italic">
            No backtest data yet for this metric
          </div>
        )}
      </div>
    </div>
  );
}
