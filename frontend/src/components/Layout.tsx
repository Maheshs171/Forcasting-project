import { NavLink, Outlet } from "react-router-dom";
import {
  LayoutDashboard, FlaskConical, Settings as SettingsIcon, Activity, Eye, Sparkles,
  Users, Stethoscope, DollarSign, Contact,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";

const mainNav = [{ to: "/", label: "Overview", icon: LayoutDashboard, end: true }];

const forecastNav = [
  { to: "/forecast/patients", label: "New Patients", icon: Users },
  { to: "/forecast/encounters", label: "Encounters", icon: Stethoscope },
  { to: "/forecast/collections", label: "Collections", icon: DollarSign },
  { to: "/forecast/contact_lenses", label: "Contact Lenses", icon: Contact },
];

const toolsNav = [
  { to: "/train", label: "Training Pipeline", icon: FlaskConical, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

function NavGroup({ title, items }: { title?: string; items: typeof mainNav }) {
  return (
    <div className="space-y-1">
      {title && <div className="px-3 pt-3 pb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">{title}</div>}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors ${
              isActive
                ? "bg-indigo-50 text-indigo-700 shadow-inner shadow-indigo-100"
                : "text-slate-500 hover:text-slate-800 hover:bg-slate-50"
            }`
          }
        >
          <item.icon size={16} strokeWidth={2} />
          {item.label}
        </NavLink>
      ))}
    </div>
  );
}

export default function Layout() {
  const { data: env } = useQuery({ queryKey: ["env"], queryFn: api.env, refetchInterval: 60_000 });

  return (
    <div className="flex h-full min-h-screen bg-[#f4f6fb]">
      <aside className="w-64 shrink-0 border-r border-slate-200 bg-white flex flex-col">
        <div className="px-5 py-5 flex items-center gap-2.5 border-b border-slate-200">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-600 to-cyan-500 flex items-center justify-center shadow-md shadow-indigo-200">
            <Sparkles size={16} className="text-white" />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-tight text-slate-900">Forecast Ops</div>
            <div className="text-[10.5px] text-slate-400 -mt-0.5">Business prediction console</div>
          </div>
        </div>

        <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
          <NavGroup items={mainNav} />
          <NavGroup title="Forecasts" items={forecastNav as typeof mainNav} />
          <NavGroup title="Tools" items={toolsNav} />
        </nav>

        <div className="px-4 py-4 border-t border-slate-200 text-[11px] text-slate-400 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Eye size={12} />
            <span className="truncate">{env?.database ?? "…"}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${env?.is_qa ? "bg-amber-500" : "bg-emerald-500"} pulse-dot`} />
            <span className="uppercase tracking-wider font-semibold text-slate-500">
              {env ? (env.is_qa ? "QA environment" : "Production") : "connecting…"}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <Topbar />
        <main className="flex-1 min-w-0 overflow-y-auto px-8 py-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Topbar() {
  const { data } = useQuery({
    queryKey: ["health-clock"],
    queryFn: api.health,
    refetchInterval: 30_000,
  });

  return (
    <header className="h-14 shrink-0 border-b border-slate-200 px-8 flex items-center justify-between bg-white">
      <div className="flex items-center gap-2 text-[13px] text-slate-500">
        <Activity size={14} className={data ? "text-emerald-500" : "text-slate-300"} />
        <span>{data ? "API connected" : "connecting to API…"}</span>
      </div>
      <div className="text-[12px] text-slate-400 mono">
        {new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
      </div>
    </header>
  );
}
