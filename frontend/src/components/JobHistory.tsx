import { useQuery } from "@tanstack/react-query";
import { api, type JobSummary } from "../lib/api";
import { StatusPill } from "./Badges";
import { timeAgo } from "../lib/format";
import { ListChecks } from "lucide-react";

export default function JobHistory({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: api.jobs,
    refetchInterval: 2000,
  });

  return (
    <div className="glass rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <ListChecks size={15} className="text-slate-400" />
        <span className="text-[13px] font-semibold text-slate-900">Run history</span>
      </div>
      <div className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
        {!jobs?.length && <div className="text-[12px] text-slate-400 italic py-6 text-center">No runs yet</div>}
        {jobs?.map((j: JobSummary) => (
          <button
            key={j.id}
            onClick={() => onSelect(j.id)}
            className={`w-full text-left rounded-lg px-3 py-2.5 transition-colors border ${
              selectedId === j.id
                ? "bg-indigo-50 border-indigo-200"
                : "border-transparent hover:bg-slate-50"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[12.5px] font-medium text-slate-800 capitalize">
                {j.kind} {j.params.metric ? `· ${j.params.metric}` : "· all metrics"}
              </span>
              <StatusPill status={j.status} />
            </div>
            <div className="flex items-center justify-between mt-1">
              <span className="text-[11px] text-slate-400">{timeAgo(j.created_at)}</span>
              {j.status === "running" && j.progress.total > 0 && (
                <span className="text-[11px] text-indigo-600 mono">
                  {j.progress.current}/{j.progress.total}
                  {j.progress.label ? ` · ${j.progress.label}` : ""}
                </span>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
