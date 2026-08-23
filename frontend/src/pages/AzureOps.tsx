import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AzureMetricReport, type AzureLeaderboardRow, type DataFrequency } from "../lib/api";
import { fmtPct, timeAgo } from "../lib/format";
import { Cloud, ExternalLink, ChevronDown, Trophy, LineChart } from "lucide-react";
import { AzureTrainForm } from "../components/AzureTrainForm";
import JobHistory from "../components/JobHistory";
import LogConsole from "../components/LogConsole";
import { StatusPill } from "../components/Badges";
import AzureForecastDetail from "../components/AzureForecastDetail";

const FREQUENCY_LABELS_LOWER: Record<DataFrequency, string> = { month: "monthly", week: "weekly", day: "daily" };

function StatusBadge({ status }: { status: string | null }) {
  const map: Record<string, string> = {
    Completed: "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500/30",
    Running: "bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-500/10 dark:text-indigo-400 dark:border-indigo-500/30",
    Failed: "bg-red-50 text-red-700 border-red-200 dark:bg-red-500/10 dark:text-red-400 dark:border-red-500/30",
  };
  const cls = map[status ?? ""] ?? "bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${cls}`}>
      {status ?? "unknown"}
    </span>
  );
}

function AccuracyBar({ value }: { value: number | null }) {
  if (value === null || value === undefined || Number.isNaN(value)) return <span className="text-slate-400 dark:text-slate-500">—</span>;
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div className="flex items-center gap-2 justify-end">
      <div className="w-16 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="mono font-semibold text-slate-700 dark:text-slate-300 w-12 text-right">{pct.toFixed(1)}%</span>
    </div>
  );
}

function LeaderboardTable({ rows }: { rows: AzureLeaderboardRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead>
          <tr className="text-left text-slate-400 dark:text-slate-500 text-[11px] uppercase tracking-wider">
            <th className="pb-2.5 font-medium">#</th>
            <th className="pb-2.5 font-medium">Algorithm</th>
            <th className="pb-2.5 font-medium text-right">Normalized RMSE</th>
            <th className="pb-2.5 font-medium text-right">R²</th>
            <th className="pb-2.5 font-medium text-right">MAPE</th>
            <th className="pb-2.5 font-medium text-right">Accuracy-equivalent</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.run_id}
              className={`border-t border-slate-100 dark:border-slate-800 ${i === 0 ? "bg-emerald-50 dark:bg-emerald-500/10" : ""}`}
            >
              <td className="py-2.5 text-slate-400 dark:text-slate-500 mono">{row.iteration}</td>
              <td className="py-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-800 dark:text-slate-200">{row.algorithm}</span>
                  {i === 0 && (
                    <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wide">
                      <Trophy size={11} /> best
                    </span>
                  )}
                </div>
              </td>
              <td className="py-2.5 text-right mono text-slate-600 dark:text-slate-400">{row.normalized_rmse.toFixed(4)}</td>
              <td className="py-2.5 text-right mono text-slate-600 dark:text-slate-400">{row.r2_score !== null ? row.r2_score.toFixed(3) : "—"}</td>
              <td className="py-2.5 text-right mono text-slate-600 dark:text-slate-400">{fmtPct(row.mape)}</td>
              <td className="py-2.5"><AccuracyBar value={row.accuracy_pct_equivalent} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MetricCard({ report }: { report: AzureMetricReport }) {
  const [expanded, setExpanded] = useState(false);
  const { data: metrics } = useQuery({ queryKey: ["metrics"], queryFn: api.metrics });
  const isMoney = metrics?.find((m) => m.key === report.metric)?.is_money ?? false;
  const best = report.best_azure;
  const shownRows = expanded ? report.leaderboard : report.leaderboard.slice(0, 5);

  return (
    <div className="glass rounded-2xl p-6 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="text-[15px] font-semibold text-slate-900 dark:text-slate-100">{report.label}</div>
          <div className="text-[11.5px] text-slate-400 dark:text-slate-500 mono mt-0.5">{report.job_name ?? "—"}</div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={report.status} />
          {report.studio_url && (
            <a
              href={report.studio_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-[11.5px] text-indigo-600 dark:text-indigo-400 hover:underline"
            >
              Open in Azure ML Studio <ExternalLink size={12} />
            </a>
          )}
        </div>
      </div>

      {/* Local vs Azure comparison */}
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 p-4">
          <div className="text-[10.5px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-1.5">
            Local pipeline winner
          </div>
          <div className="text-[15px] font-semibold text-slate-800 dark:text-slate-200 capitalize">
            {report.local_model ? report.local_model.replace("_", " ") : "no local forecast yet"}
          </div>
          {report.local_accuracy_pct !== null && report.local_accuracy_pct !== undefined && (
            <div className="text-[12px] text-slate-500 dark:text-slate-400 mt-1">
              backtested accuracy: <span className="mono font-semibold text-slate-700 dark:text-slate-300">{report.local_accuracy_pct.toFixed(1)}%</span>
            </div>
          )}
        </div>
        <div className="rounded-xl border border-indigo-200 dark:border-indigo-500/30 bg-indigo-50/40 dark:bg-indigo-500/5 p-4">
          <div className="text-[10.5px] uppercase tracking-wider text-indigo-500 dark:text-indigo-400 font-medium mb-1.5">
            Azure AutoML winner
          </div>
          <div className="text-[15px] font-semibold text-slate-800 dark:text-slate-200">
            {best ? best.algorithm : "no leaderboard yet"}
          </div>
          {best?.accuracy_pct_equivalent !== null && best?.accuracy_pct_equivalent !== undefined && (
            <div className="text-[12px] text-slate-500 dark:text-slate-400 mt-1">
              accuracy-equivalent: <span className="mono font-semibold text-slate-700 dark:text-slate-300">{best.accuracy_pct_equivalent.toFixed(1)}%</span>
              {" · "}RMSE: <span className="mono">{best.normalized_rmse.toFixed(4)}</span>
            </div>
          )}
        </div>
      </div>

      {report.leaderboard.length > 0 ? (
        <div>
          <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-2">
            Full leaderboard &middot; {report.leaderboard.length} trial{report.leaderboard.length !== 1 ? "s" : ""}
          </div>
          <LeaderboardTable rows={shownRows} />
          {report.leaderboard.length > 5 && (
            <button
              onClick={() => setExpanded((s) => !s)}
              className="mt-2 flex items-center gap-1.5 text-[11.5px] text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            >
              <ChevronDown size={12} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
              {expanded ? "Show fewer" : `Show all ${report.leaderboard.length} trials`}
            </button>
          )}
        </div>
      ) : (
        <div className="text-[12px] text-slate-400 dark:text-slate-500 italic py-4 text-center">
          Leaderboard not available yet — check the job status in Azure ML Studio.
        </div>
      )}

      {report.downloaded_models.length > 0 && (
        <div className="border-t border-slate-100 dark:border-slate-800 pt-3">
          <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-2">
            Downloaded locally &middot; top {report.downloaded_models.length} model{report.downloaded_models.length !== 1 ? "s" : ""}
          </div>
          <div className="space-y-1">
            {report.downloaded_models.map((m) => (
              <div key={m.run_id} className="flex items-center justify-between gap-2 text-[11.5px]">
                <span className="text-slate-600 dark:text-slate-400">
                  #{m.rank} <span className="font-medium text-slate-800 dark:text-slate-200">{m.algorithm}</span>
                </span>
                <span className="mono text-slate-400 dark:text-slate-500 truncate max-w-[60%]" title={m.local_path}>
                  {m.local_path}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="border-t border-slate-100 dark:border-slate-800 pt-5">
        <div className="text-[11px] uppercase tracking-wider text-slate-400 dark:text-slate-500 font-medium mb-3 flex items-center gap-1.5">
          <LineChart size={13} />
          Full forecast dashboard
        </div>
        {report.forecast_detail ? (
          <AzureForecastDetail metric={report.metric} data={report.forecast_detail} isMoney={isMoney} />
        ) : (
          <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-700 py-10 text-center text-[12.5px] text-slate-400 dark:text-slate-500">
            No future forecast generated for this run yet — retrain on Azure to get a full this-month/next-month/by-end-of-year
            breakdown with model comparisons, same as the local dashboard.
          </div>
        )}
      </div>
    </div>
  );
}

export default function AzureOps() {
  const qc = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const { data: job } = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api.job(selectedJobId!),
    enabled: !!selectedJobId,
    staleTime: Infinity, // the effect below drives all updates via setQueryData
  });

  // Same single-source-of-truth polling pattern as the local Training Pipeline page:
  // write straight into the query cache every tick, and refresh the Azure leaderboard
  // once the job finishes so results show up without a manual reload.
  useEffect(() => {
    if (!selectedJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      const j = await api.job(selectedJobId!);
      if (cancelled) return;
      qc.setQueryData(["job", selectedJobId], j);
      if (j.status === "completed" || j.status === "failed") {
        qc.invalidateQueries({ queryKey: ["azure-latest"] });
        qc.invalidateQueries({ queryKey: ["jobs"] });
        return;
      }
      timer = setTimeout(tick, 1500);
    }
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [selectedJobId, qc]);

  function handleStarted(jobId: string) {
    setSelectedJobId(jobId);
    qc.invalidateQueries({ queryKey: ["jobs"] });
  }

  const [frequency, setFrequency] = useState<DataFrequency>("month");

  const { data, isLoading, error } = useQuery({
    queryKey: ["azure-latest", frequency],
    queryFn: () => api.azureLatest(frequency),
    retry: false,
  });

  return (
    <div className="max-w-6xl mx-auto space-y-7">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-slate-900 dark:text-slate-100 flex items-center gap-2.5">
            <Cloud size={22} className="text-indigo-500" />
            Azure Ops
          </h1>
          <p className="text-[13px] text-slate-400 dark:text-slate-500 mt-1">
            Train directly on Azure AutoML — fetches and cleans data from the DB, uploads it, auto-starts compute,
            submits the job, and pulls back every algorithm Azure tried per metric, ranked by held-out error, next to
            this project's own backtested pick.
          </p>
        </div>
        {data?.generated_at && (
          <div className="text-[11.5px] text-slate-400 dark:text-slate-500">
            Report generated {timeAgo(data.generated_at)}
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        <AzureTrainForm onStarted={handleStarted} frequency={frequency} onFrequencyChange={setFrequency} />
        <JobHistory selectedId={selectedJobId} onSelect={setSelectedJobId} />
      </div>

      {selectedJobId && (
        <div className="glass rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">Azure training run</span>
            {job && <StatusPill status={job.status} />}
          </div>
          {job?.progress?.total ? (
            <div className="space-y-1">
              <div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-500"
                  style={{ width: `${(job.progress.current / job.progress.total) * 100}%` }}
                />
              </div>
              {job.progress.label && (
                <div className="text-[11px] text-slate-400 dark:text-slate-500">
                  Training {job.progress.label} ({job.progress.current}/{job.progress.total})
                </div>
              )}
            </div>
          ) : null}
          <LogConsole lines={job?.logs ?? []} />
          {job?.error && (
            <div className="rounded-lg border border-red-200 dark:border-red-500/30 bg-red-50 dark:bg-red-500/10 px-3 py-2 text-[12px] text-red-700 dark:text-red-400 whitespace-pre-wrap">
              {job.error}
            </div>
          )}
        </div>
      )}

      {isLoading && (
        <div className="glass rounded-2xl p-10 text-center text-[13px] text-slate-400 dark:text-slate-500">
          Loading Azure AutoML report…
        </div>
      )}

      {error && (
        <div className="glass rounded-2xl p-10 text-center space-y-2">
          <div className="text-[13px] text-slate-500 dark:text-slate-400">
            No {FREQUENCY_LABELS_LOWER[frequency]} Azure AutoML report found yet.
          </div>
          <div className="text-[11.5px] text-slate-400 dark:text-slate-500 mono">
            python azure_automl.py --metric all --horizon 12{frequency !== "month" ? ` --freq ${frequency}` : ""}
          </div>
        </div>
      )}

      {data && (
        <div className="space-y-6">
          {Object.values(data.data).map((report) => (
            <MetricCard key={report.metric} report={report} />
          ))}
        </div>
      )}
    </div>
  );
}
