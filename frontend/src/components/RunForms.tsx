import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, TestTube2 } from "lucide-react";
import { api, type MetricMeta, type ModelMeta, type DataFrequency } from "../lib/api";

const FREQUENCY_LABELS: Record<DataFrequency, string> = { month: "Monthly", week: "Weekly", day: "Daily" };

function FrequencyToggle({ value, onChange }: { value: DataFrequency; onChange: (f: DataFrequency) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 p-0.5">
      {(Object.keys(FREQUENCY_LABELS) as DataFrequency[]).map((f) => (
        <button
          key={f}
          type="button"
          onClick={() => onChange(f)}
          className={`rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors ${
            value === f ? "bg-indigo-600 text-white shadow-sm" : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
          }`}
        >
          {FREQUENCY_LABELS[f]}
        </button>
      ))}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">{label}</span>
      {children}
    </label>
  );
}

const selectCls =
  "w-full rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 px-3 py-2 text-[13px] text-slate-800 dark:text-slate-200 focus:outline-none focus:border-indigo-400/50 focus:bg-slate-100 dark:focus:bg-slate-800 transition-colors [color-scheme:light] dark:[color-scheme:dark]";

export function PredictForm({ onStarted }: { onStarted: (jobId: string) => void }) {
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const { data: models } = useQuery({ queryKey: ["models"], queryFn: api.models });
  const { data: defaults } = useQuery({ queryKey: ["defaults"], queryFn: api.configDefaults });

  const [metric, setMetric] = useState<string>("");
  const [model, setModel] = useState<string>("");
  const [freq, setFreq] = useState<DataFrequency>("month");
  const [startYear, setStartYear] = useState<number | "">("");
  const [endDate, setEndDate] = useState<string>("");
  const [historyEndDate, setHistoryEndDate] = useState<string>("");
  const [months, setMonths] = useState<number | "">("");

  const mutation = useMutation({
    mutationFn: () =>
      api.runPredict({
        metric: metric || null,
        model: model || null,
        freq,
        start_year: startYear === "" ? defaults?.start_year ?? 2019 : startYear,
        end_date: endDate || null,
        history_end_date: historyEndDate || null,
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
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
            <Play size={15} className="text-indigo-600 dark:text-indigo-400" />
          </div>
          <div>
            <div className="text-[13.5px] font-semibold text-slate-900 dark:text-slate-100">Run forecast</div>
            <div className="text-[11.5px] text-slate-400 dark:text-slate-500">Backtests + generates the business forecast</div>
          </div>
        </div>
        <FrequencyToggle value={freq} onChange={setFreq} />
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
        <Field label="Exclude data after (optional)">
          <input
            type="date"
            className={selectCls}
            value={historyEndDate}
            onChange={(e) => setHistoryEndDate(e.target.value)}
            title="Use this if a recent DB backup/restore left the latest month(s) incomplete — trims training history to this date instead of trusting the gap as real data"
          />
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
  const [freq, setFreq] = useState<DataFrequency>("month");
  const [startYear, setStartYear] = useState<number | "">("");

  const mutation = useMutation({
    mutationFn: () =>
      api.runValidate({
        metric: metric || null,
        freq,
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
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="h-8 w-8 rounded-lg bg-cyan-50 dark:bg-cyan-500/10 flex items-center justify-center">
            <TestTube2 size={15} className="text-cyan-600 dark:text-cyan-400" />
          </div>
          <div>
            <div className="text-[13.5px] font-semibold text-slate-900 dark:text-slate-100">Run backtest only</div>
            <div className="text-[11.5px] text-slate-400 dark:text-slate-500">Compares all candidate models on real held-out accuracy</div>
          </div>
        </div>
        <FrequencyToggle value={freq} onChange={setFreq} />
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
