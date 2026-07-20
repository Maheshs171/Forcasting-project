import { motion } from "framer-motion";
import type { ReactNode } from "react";

interface Props {
  label: string;
  value: string;
  sub?: string;
  range?: string;
  icon?: ReactNode;
  accent?: "indigo" | "cyan" | "emerald" | "amber";
  delay?: number;
}

const accentMap = {
  indigo: "from-indigo-200/60 to-indigo-100/0 text-indigo-600",
  cyan: "from-cyan-200/60 to-cyan-100/0 text-cyan-600",
  emerald: "from-emerald-200/60 to-emerald-100/0 text-emerald-600",
  amber: "from-amber-200/60 to-amber-100/0 text-amber-600",
};

export default function KpiCard({ label, value, sub, range, icon, accent = "indigo", delay = 0 }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay }}
      className="glass rounded-2xl p-5 relative overflow-hidden group hover:border-slate-300 transition-colors"
    >
      <div className={`absolute -top-8 -right-8 h-28 w-28 rounded-full bg-gradient-to-br ${accentMap[accent]} blur-2xl opacity-70 group-hover:opacity-100 transition-opacity`} />
      <div className="relative">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11.5px] font-medium uppercase tracking-wider text-slate-400">{label}</span>
          {icon && <span className={accentMap[accent].split(" ").pop()}>{icon}</span>}
        </div>
        <div className="text-[26px] font-semibold tracking-tight text-slate-900 mono leading-none">{value}</div>
        {sub && <div className="text-[12px] text-slate-500 mt-2">{sub}</div>}
        {range && <div className="text-[11px] text-slate-400 mt-1 mono">{range}</div>}
      </div>
    </motion.div>
  );
}
