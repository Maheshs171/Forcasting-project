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
import type { ForecastPoint } from "../lib/api";
import { fmtCompact } from "../lib/format";

interface Props {
  points: ForecastPoint[];
  isMoney?: boolean;
  height?: number;
  color?: string;
}

export default function TrendChart({ points, isMoney = false, height = 300, color = "#4f46e5" }: Props) {
  const data = points.map((p) => ({
    label: p.label,
    predicted: p.predicted,
    band: [p.low, p.high],
    low: p.low,
    high: p.high,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="bandFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.18} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="rgba(15,23,42,0.06)" vertical={false} />
        <XAxis
          dataKey="label"
          tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 11 }}
          axisLine={{ stroke: "rgba(15,23,42,0.1)" }}
          tickLine={false}
          interval={Math.max(0, Math.floor(data.length / 8))}
        />
        <YAxis
          tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => fmtCompact(v, isMoney)}
          width={56}
        />
        <Tooltip
          contentStyle={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 10,
            fontSize: 12,
            boxShadow: "0 8px 24px -8px rgba(15,23,42,0.15)",
          }}
          labelStyle={{ color: "#334155", marginBottom: 4, fontWeight: 600 }}
          formatter={(value, name) => {
            const v = typeof value === "number" ? value : Number(value);
            if (name === "high" || name === "low") return [fmtCompact(v, isMoney), String(name)];
            return [fmtCompact(v, isMoney), "forecast"];
          }}
        />
        <Area type="monotone" dataKey="high" stroke="none" fill="url(#bandFill)" isAnimationActive={false} />
        <Area type="monotone" dataKey="low" stroke="none" fill="#ffffff" isAnimationActive={false} fillOpacity={1} />
        <Line
          type="monotone"
          dataKey="predicted"
          stroke={color}
          strokeWidth={2.5}
          dot={{ r: 3, fill: color, strokeWidth: 0 }}
          activeDot={{ r: 5 }}
          isAnimationActive
        />
        {data.length > 0 && <ReferenceLine x={data[0].label} stroke="rgba(15,23,42,0.15)" strokeDasharray="3 3" />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
