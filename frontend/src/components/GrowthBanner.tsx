import { ArrowUpRight, ArrowDownRight } from "lucide-react";

function GrowthStat({ label, pct }: { label: string; pct: number | null | undefined }) {
  const has = pct !== null && pct !== undefined && !Number.isNaN(pct);
  const positive = has && pct! >= 0;
  return (
    <div className="flex-1 flex items-center justify-center gap-3 py-4">
      <span className="text-[13px] font-semibold text-white/90 uppercase tracking-wide">{label}</span>
      <span className={`inline-flex items-center gap-1 text-[20px] font-bold ${has ? (positive ? "text-emerald-300" : "text-rose-300") : "text-white/50"}`}>
        {has ? (
          <>
            {positive ? <ArrowUpRight size={20} /> : <ArrowDownRight size={20} />}
            {Math.abs(pct!).toFixed(2)}%
          </>
        ) : (
          "n/a"
        )}
      </span>
    </div>
  );
}

export default function GrowthBanner({ mtdPct, ytdPct }: { mtdPct?: number | null; ytdPct?: number | null }) {
  return (
    <div className="rounded-2xl overflow-hidden shadow-lg shadow-slate-900/10">
      <div className="bg-gradient-to-r from-[#1e2a5e] via-[#2d3a7a] to-[#1e2a5e] flex divide-x divide-white/10">
        <GrowthStat label="Overall % growth MTD" pct={mtdPct} />
        <GrowthStat label="Overall % growth YTD" pct={ytdPct} />
      </div>
    </div>
  );
}
