import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, TestTube2 } from "lucide-react";
import { api, type MetricMeta, type ModelMeta } from "../lib/api";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
      {children}
    </label>
  );
}

const selectCls =
  "w-full rounded-lg bg-slate-50 border border-slate-200 px-3 py-2 text-[13px] text-slate-800 focus:outline-none focus:border-indigo-400/50 focus:bg-slate-100 transition-colors";

export function PredictForm({ onStarted }: { onStarted: (jobId: string) => void }) {
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models });
  const { data: defaults } = useQuery({ queryKey: ["defaults"], queryFn: api.configDefaults });

  const [metric, setMetric] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [startYear, setStartYear] = useState<number | "">("");
  const [endDate, setEndDate] = useState<string>("");
  const [months, setMonths] = useState<number | "">("");

  const mutation = useMutation({
    mutationFn: () =>
      api.runPredict({
        metric: metric || null,
        model: model || null,
        start_year: startYear === "" ? defaults?.start_year ?? 2019 : startYear,
        end_date: endDate || null,
        months: months === "" ? defaults?.months ?? 12 : months,
        country: defaults?.country ?? "US",
      }),
    onSuccess: (job) => {
      onStarted(job.id);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 rounded-lg bg-indigo-50 flex items-center justify-center">
          <Play size={15} className="text-indigo-600" />
        </div>
        <div>
          <div className="text-[13.5px] font-semibold text-slate-900">Run forecast</div>
          <div className="text-[11.5px] text-slate-400">Backtests + generates the business forecast</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Metric">
          <select className={selectCls} value={metric} onChange={(e) => setMetric(e.target.value)}>
            <option value="">All metrics</option>
            {metrics?.map((m: MetricMeta) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Model">
          <select className={selectCls} value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">Auto (backtested best)</option>
            {models?.map((m: ModelMeta) => (
              <option key={m.key} value={m.key}>
                {m.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Start year">
          <input
            type="number"
            className={selectCls}
            placeholder={String(defaults?.start_year ?? 2019)}
            value={startYear}
            onChange={(e) => setStartYear(e.target.value ? Number(e.target.value) : "")}
          />
        </Field>
        <Field label="Min. months ahead">
          <input
            type="number"
            className={selectCls}
            placeholder={String(defaults?.months ?? 12)}
            value={months}
            onChange={(e) => setMonths(e.target.value ? Number(e.target.value) : "")}
          />
        </Field>
        <Field label="Forecast until (optional)">
          <input type="date" className={selectCls} value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </Field>
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-500 px-4 py-2.5 text-[13px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-50 transition-colors shadow-lg shadow-indigo-900/30"
      >
        <Play size={14} />
        {mutation.isPending ? "Starting…" : "Run forecast"}
      </button>
    </div>
  );
}

export function ValidateForm({ onStarted }: { onStarted: (jobId: string) => void }) {
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const { data: defaults } = useQuery({ queryKey: ["defaults"], queryFn: api.configDefaults });

  const [metric, setMetric] = useState<string>("");
  const [startYear, setStartYear] = useState<number | "">("");

  const mutation = useMutation({
    mutationFn: () =>
      api.runValidate({
        metric: metric || null,
        start_year: startYear === "" ? defaults?.start_year ?? 2019 : startYear,
        country: defaults?.country ?? "US",
      }),
    onSuccess: (job) => {
      onStarted(job.id);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 rounded-lg bg-cyan-50 flex items-center justify-center">
          <TestTube2 size={15} className="text-cyan-600" />
        </div>
        <div>
          <div className="text-[13.5px] font-semibold text-slate-900">Run backtest only</div>
          <div className="text-[11.5px] text-slate-400">Compares all candidate models on real held-out accuracy</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Metric">
          <select className={selectCls} value={metric} onChange={(e) => setMetric(e.target.value)}>
            <option value="">All metrics</option>
            {metrics?.map((m: MetricMeta) => (
              <option key={m.key} value={m.key}>
                {m.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Start year">
          <input
            type="number"
            className={selectCls}
            placeholder={String(defaults?.start_year ?? 2019)}
            value={startYear}
            onChange={(e) => setStartYear(e.target.value ? Number(e.target.value) : "")}
          />
        </Field>
      </div>

      <button
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-cyan-500/90 px-4 py-2.5 text-[13px] font-semibold text-white hover:bg-cyan-400 disabled:opacity-50 transition-colors shadow-lg shadow-cyan-900/30"
      >
        <TestTube2 size={14} />
        {mutation.isPending ? "Starting…" : "Run backtest"}
      </button>
    </div>
  );
}
