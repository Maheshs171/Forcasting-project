import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CloudUpload, ChevronDown, AlertTriangle, HardDriveDownload } from "lucide-react";
import { api, type MetricMeta, type DataFrequency } from "../lib/api";

const FREQUENCY_LABELS: Record<DataFrequency, string> = { month: "Monthly", week: "Weekly", day: "Daily" };

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

export function AzureTrainForm({
  onStarted,
  frequency,
  onFrequencyChange,
}: {
  onStarted: (jobId: string) => void;
  frequency: DataFrequency;
  onFrequencyChange: (f: DataFrequency) => void;
}) {
  const qc = useQueryClient();
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const { data: defaults } = useQuery({ queryKey: ["defaults"], queryFn: api.configDefaults });
  const { data: status } = useQuery({ queryKey: ["azure-status"], queryFn: api.azureStatus });

  const [metric, setMetric] = useState<string>("");
  const [startYear, setStartYear] = useState<number | "">("");
  const [horizon, setHorizon] = useState<number | "">("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [maxTrials, setMaxTrials] = useState<number>(25);
  const [maxConcurrent, setMaxConcurrent] = useState<number>(1);
  const [timeoutMinutes, setTimeoutMinutes] = useState<number>(90);
  const [trialTimeoutMinutes, setTrialTimeoutMinutes] = useState<number>(20);

  const mutation = useMutation({
    mutationFn: () =>
      api.runAzureTrain({
        metric: metric || "all",
        freq: frequency,
        start_year: startYear === "" ? defaults?.start_year ?? 2019 : startYear,
        horizon: horizon === "" ? defaults?.months ?? 12 : horizon,
        max_trials: maxTrials,
        max_concurrent_trials: maxConcurrent,
        timeout_minutes: timeoutMinutes,
        trial_timeout_minutes: trialTimeoutMinutes,
      }),
    onSuccess: (job) => {
      onStarted(job.id);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  // Regenerates the dashboard purely from models/azure_downloads/ + a
  // previously-saved outputs/azure_automl*.json — no Azure connection, no
  // credentials, no new training. Meant for someone who was handed a copy
  // of those folders (e.g. a teammate without Azure ML access) and just
  // wants to view/re-view the report from already fine-tuned models.
  const fromDownloadsMutation = useMutation({
    mutationFn: () =>
      api.runAzureForecastFromDownloads({
        metric: metric || "all",
        freq: frequency,
        start_year: startYear === "" ? defaults?.start_year ?? 2019 : startYear,
        horizon: horizon === "" ? defaults?.months ?? 12 : horizon,
      }),
    onSuccess: (job) => {
      onStarted(job.id);
      qc.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const disabled = mutation.isPending || !status?.configured;
  const fromDownloadsDisabled = fromDownloadsMutation.isPending;

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 rounded-lg bg-indigo-50 dark:bg-indigo-500/10 flex items-center justify-center">
          <CloudUpload size={15} className="text-indigo-600 dark:text-indigo-400" />
        </div>
        <div>
          <div className="text-[13.5px] font-semibold text-slate-900 dark:text-slate-100">Train on Azure</div>
          <div className="text-[11.5px] text-slate-400 dark:text-slate-500">
            Fetches + cleans from the DB, uploads to Azure, auto-starts compute, submits AutoML, waits for results
          </div>
        </div>
      </div>

      {status && !status.configured && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-400">
          <AlertTriangle size={14} className="shrink-0 mt-0.5" />
          <span>
            Azure ML isn't configured yet — missing {status.missing.join(", ")} in <code className="mono">.env</code>. See
            the README's "Azure AutoML setup" section.
          </span>
        </div>
      )}

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
        <Field label="Frequency">
          <select className={selectCls} value={frequency} onChange={(e) => onFrequencyChange(e.target.value as DataFrequency)}>
            {(Object.keys(FREQUENCY_LABELS) as DataFrequency[]).map((f) => (
              <option key={f} value={f}>
                {FREQUENCY_LABELS[f]}
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
        <Field label="Forecast horizon (months)">
          <input
            type="number"
            className={selectCls}
            placeholder={String(defaults?.months ?? 12)}
            value={horizon}
            onChange={(e) => setHorizon(e.target.value ? Number(e.target.value) : "")}
          />
        </Field>
        <Field label="Compute target">
          <input className={`${selectCls} opacity-60`} value={status?.compute_name ?? "—"} disabled />
        </Field>
      </div>

      <button
        type="button"
        onClick={() => setShowAdvanced((s) => !s)}
        className="flex items-center gap-1.5 text-[11.5px] text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
      >
        <ChevronDown size={12} className={`transition-transform ${showAdvanced ? "rotate-180" : ""}`} />
        Advanced AutoML limits
      </button>
      {showAdvanced && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Max trials">
            <input type="number" className={selectCls} value={maxTrials} onChange={(e) => setMaxTrials(Number(e.target.value) || 25)} />
          </Field>
          <Field label="Max concurrent trials">
            <input
              type="number"
              className={selectCls}
              value={maxConcurrent}
              onChange={(e) => setMaxConcurrent(Number(e.target.value) || 1)}
              title="Raise only if the compute target is a multi-node Compute Cluster"
            />
          </Field>
          <Field label="Job timeout (minutes)">
            <input type="number" className={selectCls} value={timeoutMinutes} onChange={(e) => setTimeoutMinutes(Number(e.target.value) || 90)} />
          </Field>
          <Field label="Per-trial timeout (minutes)">
            <input
              type="number"
              className={selectCls}
              value={trialTimeoutMinutes}
              onChange={(e) => setTrialTimeoutMinutes(Number(e.target.value) || 20)}
            />
          </Field>
        </div>
      )}

      <button
        onClick={() => mutation.mutate()}
        disabled={disabled}
        className="w-full inline-flex items-center justify-center gap-2 rounded-lg bg-indigo-500 px-4 py-2.5 text-[13px] font-semibold text-white hover:bg-indigo-400 disabled:opacity-50 transition-colors shadow-lg shadow-indigo-900/30"
      >
        <CloudUpload size={14} />
        {mutation.isPending ? "Starting…" : "Train on Azure"}
      </button>
      {mutation.isError && (
        <div className="text-[12px] text-red-600 dark:text-red-400">
          {(mutation.error as Error)?.message ?? "Failed to start job"}
        </div>
      )}
      <p className="text-[11px] text-slate-400 dark:text-slate-500 leading-relaxed">
        Each metric's AutoML job can take 20-90+ minutes on Azure — this runs synchronously and streams live progress
        below; the leaderboard refreshes automatically once it's done.
      </p>

      <div className="border-t border-slate-100 dark:border-slate-800 pt-4 space-y-2">
        <button
          onClick={() => fromDownloadsMutation.mutate()}
          disabled={fromDownloadsDisabled}
          className="w-full inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 px-4 py-2.5 text-[13px] font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-50 transition-colors"
        >
          <HardDriveDownload size={14} />
          {fromDownloadsMutation.isPending ? "Rebuilding…" : "Run forecast from downloaded models"}
        </button>
        {fromDownloadsMutation.isError && (
          <div className="text-[12px] text-red-600 dark:text-red-400">
            {(fromDownloadsMutation.error as Error)?.message ?? "Failed to start job"}
          </div>
        )}
        <p className="text-[11px] text-slate-400 dark:text-slate-500 leading-relaxed">
          Regenerates the dashboard from models already downloaded to <code className="mono">models/azure_downloads/</code> —
          no Azure connection or credentials needed, finishes in seconds. Use this if you were handed someone else's
          fine-tuned models (that folder + <code className="mono">outputs/</code> + <code className="mono">data/cache/</code>)
          and just want to view the report without training again.
        </p>
      </div>
    </div>
  );
}
