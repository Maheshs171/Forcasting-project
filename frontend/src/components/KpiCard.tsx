import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";

interface Props {
  label: string;
  value: string;
  sub?: string;
  range?: string;
  icon?: ReactNode;
  accent?: "indigo" | "cyan" | "emerald" | "amber";
  delay?: number;
  trend?: number[];
  trendPct?: number | null;
}

const accentMap = {
  indigo: { glow: "from-indigo-200/60 to-indigo-100/0 dark:from-indigo-500/20 dark:to-indigo-500/0", icon: "text-indigo-600 dark:text-indigo-400", line: "#4f46e5" },
  cyan: { glow: "from-cyan-200/60 to-cyan-100/0 dark:from-cyan-500/20 dark:to-cyan-500/0", icon: "text-cyan-600 dark:text-cyan-400", line: "#0891b2" },
  emerald: { glow: "from-emerald-200/60 to-emerald-100/0 dark:from-emerald-500/20 dark:to-emerald-500/0", icon: "text-emerald-600 dark:text-emerald-400", line: "#059669" },
  amber: { glow: "from-amber-200/60 to-amber-100/0 dark:from-amber-500/20 dark:to-amber-500/0", icon: "text-amber-600 dark:text-amber-400", line: "#d97706" },
};

export default function KpiCard({ label, value, sub, range, icon, accent = "indigo", delay = 0, trend, trendPct }: Props) {
  const a = accentMap[accent];
  const sparkData = trend?.map((v, i) => ({ i, v }));

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
      className="glass rounded-2xl p-5 relative overflow-hidden group hover:border-slate-300 dark:hover:border-slate-600 transition-colors"
    >
      <div className={`absolute -top-8 -right-8 h-28 w-28 rounded-full bg-gradient-to-br ${a.glow} blur-2xl opacity-70 group-hover:opacity-100 transition-opacity`} />
      <div className="relative">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11.5px] font-medium uppercase tracking-wider text-slate-400 dark:text-slate-500">{label}</span>
          {icon && <span className={a.icon}>{icon}</span>}
        </div>
        <div className="flex items-end justify-between gap-3">
          <div>
            <div className="text-[26px] font-semibold tracking-tight text-slate-900 dark:text-slate-100 mono leading-none">{value}</div>
            {sub && <div className="text-[12px] text-slate-500 dark:text-slate-400 mt-2">{sub}</div>}
            {range && <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-1 mono">{range}</div>}
            {trendPct != null && (
              <div className={`inline-flex items-center gap-0.5 text-[11px] font-medium mt-2 ${trendPct >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400"}`}>
                {trendPct >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                {Math.abs(trendPct).toFixed(1)}%
              </div>
            )}
          </div>
          {sparkData && sparkData.length > 1 && (
            <div className="w-20 h-10 shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={sparkData} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id={`spark-${label.replace(/\s/g, "")}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={a.line} stopOpacity={0.35} />
                      <stop offset="100%" stopColor={a.line} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <Area type="monotone" dataKey="v" stroke={a.line} strokeWidth={1.75} fill={`url(#spark-${label.replace(/\s/g, "")})`} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
