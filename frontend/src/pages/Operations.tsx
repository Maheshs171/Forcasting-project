import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PredictForm, ValidateForm } from "../components/RunForms";
import JobHistory from "../components/JobHistory";
import LogConsole from "../components/LogConsole";
import { StatusPill } from "../components/Badges";
import BacktestTable from "../components/BacktestTable";
import BacktestBarChart from "../components/BacktestBarChart";
import PipelineStepper from "../components/PipelineStepper";
import DataQualityPreview from "../components/DataQualityPreview";
import { motion } from "framer-motion";
import { Gauge, ChevronDown } from "lucide-react";

export default function Operations() {
  const qc = useQueryClient();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const { data: job } = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api.job(selectedJobId!),
    enabled: !!selectedJobId,
    staleTime: Infinity, // the effect below drives all updates via setQueryData
  });

  // Single source of truth for polling a job: writes straight into the query
  // cache on every tick so the UI can never end up displaying data from a
  // different (stale) fetch than what's actually stored.
  useEffect(() => {
    if (!selectedJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      const j = await api.job(selectedJobId!);
      if (cancelled) return;
      qc.setQueryData(["job", selectedJobId], j);
      if (j.status === "completed" || j.status === "failed") {
        qc.invalidateQueries({ queryKey: ["all-forecasts"] });
        qc.invalidateQueries({ queryKey: ["backtest-latest"] });
        qc.invalidateQueries({ queryKey: ["jobs"] });
        return;
      }
      timer = setTimeout(tick, 900);
    }
    tick();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [selectedJobId, qc]);

  const { data: backtestReport } = useQuery({
    queryKey: ["backtest-latest"],
    queryFn: api.backtest,
    retry: false,
  });

  function handleStarted(jobId: string) {
    setSelectedJobId(jobId);
    qc.invalidateQueries({ queryKey: ["jobs"] });
  }

  return (
    <div className="max-w-6xl mx-auto space-y-7">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-slate-900">Training Pipeline</h1>
        <p className="text-[13px] text-slate-400 mt-1">
          Fetch from the database, clean the data, train every candidate model, and compare results — all from
          here. Run backtests and forecasts directly and watch them run live below.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <PredictForm onStarted={handleStarted} />
        <ValidateForm onStarted={handleStarted} />
      </div>

      <div className="glass rounded-2xl p-6">
        <div className="text-[11px] uppercase tracking-wider text-slate-400 font-medium mb-4">Pipeline progress</div>
        <PipelineStepper job={job} />
      </div>

      <DataQualityPreview />

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-5">
        <motion.div layout className="glass rounded-2xl p-5 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-[13px] font-semibold text-slate-900">
              {job ? `${job.kind === "predict" ? "Forecast" : "Backtest"} run` : "Live run output"}
            </span>
            {job && <StatusPill status={job.status} />}
          </div>
          {job?.progress?.total ? (
            <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-indigo-500 to-cyan-400 transition-all duration-500"
                style={{ width: `${(job.progress.current / job.progress.total) * 100}%` }}
              />
            </div>
          ) : null}
          <LogConsole lines={job?.logs ?? []} />
          {job?.error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-[12px] text-red-700 whitespace-pre-wrap">
              {job.error}
            </div>
          )}
        </motion.div>

        <JobHistory selectedId={selectedJobId} onSelect={setSelectedJobId} />
      </div>

      <div className="glass rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-1">
          <Gauge size={15} className="text-slate-400" />
          <span className="text-[13px] font-semibold text-slate-900">Step 4 &middot; Evaluation — which model is best, per metric</span>
        </div>
        <p className="text-[11.5px] text-slate-400 mb-4">
          Lower score = more accurate on real held-out data. The green bar is the model actually used in production.
        </p>
        {!backtestReport && <div className="text-[12px] text-slate-400 italic py-6 text-center">No backtest run yet</div>}
        {backtestReport && (
          <div className="space-y-8">
            {Object.entries(backtestReport.data).map(([metric, report]) => (
              <MetricEvaluation key={metric} metric={metric} report={report} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricEvaluation({ metric, report }: { metric: string; report: import("../lib/api").BacktestReport }) {
  const [showTable, setShowTable] = useState(false);
  return (
    <div>
      <div className="text-[12.5px] font-semibold text-slate-700 mb-2 capitalize">{metric.replace("_", " ")}</div>
      <BacktestBarChart report={report} />
      <button
        onClick={() => setShowTable((s) => !s)}
        className="mt-2 flex items-center gap-1.5 text-[11.5px] text-slate-400 hover:text-slate-600 transition-colors"
      >
        <ChevronDown size={12} className={`transition-transform ${showTable ? "rotate-180" : ""}`} />
        Detailed numbers
      </button>
      {showTable && (
        <div className="mt-2">
          <BacktestTable report={report} />
        </div>
      )}
    </div>
  );
}
