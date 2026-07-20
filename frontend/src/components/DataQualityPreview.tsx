import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ComposedChart, Line, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { ScanSearch, Loader2 } from "lucide-react";
import { api } from "../lib/api";

export default function DataQualityPreview() {
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const [metric, setMetric] = useState("patients");

  const mutation = useMutation({ mutationFn: () => api.dataQuality(metric) });

  const report = mutation.data;
  const chartData = report
    ? report.raw_monthly.map((p) => {
        const excluded = report.excluded.find((e) => e.month === p.month);
        return { label: p.label, raw: p.value, excludedValue: excluded ? p.value : null };
      })
    : [];

  return (
    <div className="glass rounded-2xl p-6">
      <div className="flex items-center justify-between flex-wrap gap-3 mb-4">
        <div>
          <div className="text-[13px] font-semibold text-slate-900">Step 2 preview &middot; before / after cleaning</div>
          <div className="text-[11.5px] text-slate-400 mt-0.5">Pulls live from the database — shows exactly which months get excluded and why</div>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="rounded-lg bg-slate-50 border border-slate-200 px-3 py-1.5 text-[12.5px] text-slate-700"
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
          >
            {metrics?.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
          <button
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-800 px-3 py-1.5 text-[12.5px] font-medium text-white hover:bg-slate-700 disabled:opacity-50 transition-colors"
          >
            {mutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <ScanSearch size={13} />}
            Preview
          </button>
        </div>
      </div>

      {mutation.isError && (
        <div className="text-[12.5px] text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          Could not reach the database right now — try again in a moment.
        </div>
      )}

      {report && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div className="text-[11px] text-slate-400">Raw months</div>
              <div className="text-[19px] font-semibold text-slate-900 mono">{report.raw_count}</div>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3">
              <div className="text-[11px] text-emerald-700">Kept (clean)</div>
              <div className="text-[19px] font-semibold text-emerald-800 mono">{report.cleaned_count}</div>
            </div>
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3">
              <div className="text-[11px] text-red-700">Excluded as anomalies</div>
              <div className="text-[19px] font-semibold text-red-700 mono">{report.excluded_count}</div>
            </div>
          </div>

          <ResponsiveContainer width="100%" height={220}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="rgba(15,23,42,0.06)" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 10 }} axisLine={{ stroke: "rgba(15,23,42,0.1)" }} tickLine={false} interval={Math.max(0, Math.floor(chartData.length / 8))} />
              <YAxis tick={{ fill: "rgba(15,23,42,0.45)", fontSize: 10 }} axisLine={false} tickLine={false} width={48} />
              <Tooltip contentStyle={{ background: "#fff", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12 }} />
              <Line type="monotone" dataKey="raw" stroke="#4f46e5" strokeWidth={2} dot={{ r: 2.5, fill: "#4f46e5" }} name="Monthly value" isAnimationActive={false} />
              <Scatter dataKey="excludedValue" fill="#dc2626" name="Excluded anomaly" shape="circle" />
            </ComposedChart>
          </ResponsiveContainer>

          {report.notes.length > 0 && (
            <div className="space-y-1">
              {report.notes.map((n, i) => (
                <div key={i} className="text-[12px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-1.5">
                  {n}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
