import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  LayoutDashboard, FlaskConical, Settings as SettingsIcon, Activity, Eye, Sparkles,
  Users, Stethoscope, DollarSign, Contact, Microscope, Search, Sun, Moon, ChevronRight, Cloud,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useTheme } from "../lib/useTheme";
import CommandPalette from "./CommandPalette";

const mainNav = [{ to: "/", label: "Overview", icon: LayoutDashboard, end: true }];

const forecastNav = [
  { to: "/forecast/patients", label: "New Patients", icon: Users },
  { to: "/forecast/encounters", label: "Encounters", icon: Stethoscope },
  { to: "/forecast/collections", label: "Collections", icon: DollarSign },
  { to: "/forecast/contact_lenses", label: "Contact Lenses", icon: Contact },
];

const toolsNav = [
  { to: "/explore", label: "Data Explorer", icon: Microscope, end: false },
  { to: "/train", label: "Training Pipeline", icon: FlaskConical, end: false },
  { to: "/azure", label: "Azure Ops", icon: Cloud, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

const PAGE_TITLES: Record<string, string> = {
  "/": "Overview",
  "/explore": "Data Explorer",
  "/train": "Training Pipeline",
  "/azure": "Azure Ops",
  "/settings": "Settings",
};

function NavGroup({ title, items }: { title?: string; items: typeof mainNav }) {
  return (
    <div className="space-y-0.5">
      {title && <div className="px-3 pt-4 pb-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">{title}</div>}
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            `relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
              isActive
                ? "bg-indigo-500/8 text-indigo-700 dark:bg-indigo-400/10 dark:text-indigo-300"
                : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800/60"
            }`
          }
        >
          {({ isActive }) => (
            <>
              {isActive && <span className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full bg-indigo-600 dark:bg-indigo-400" />}
              <item.icon size={16} strokeWidth={2} />
              {item.label}
            </>
          )}
        </NavLink>
      ))}
    </div>
  );
}

export default function Layout() {
  const { data: env } = useQuery({ queryKey: ["env"], queryFn: api.env, refetchInterval: 60_000 });
  const { theme, toggle } = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const pageTitle = PAGE_TITLES[location.pathname] ?? (location.pathname.startsWith("/forecast/") ? "Forecast" : "");

  return (
    <div className="flex h-full min-h-screen bg-[#f4f6fb] dark:bg-[#0b0f1a] transition-colors">
      <aside className="w-64 shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-[#0e1420] flex flex-col transition-colors">
        <div className="px-5 py-5 flex items-center gap-2.5 border-b border-slate-200 dark:border-slate-800">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-indigo-600 to-cyan-500 flex items-center justify-center shadow-md shadow-indigo-200 dark:shadow-indigo-900/40">
            <Sparkles size={16} className="text-white" />
          </div>
          <div>
            <div className="text-[13px] font-semibold tracking-tight text-slate-900 dark:text-slate-100">Forecast Ops</div>
            <div className="text-[10.5px] text-slate-400 dark:text-slate-500 -mt-0.5">Business prediction console</div>
          </div>
        </div>

        <div className="px-3 pt-3">
          <button
            onClick={() => setPaletteOpen(true)}
            className="w-full flex items-center gap-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/60 px-3 py-2 text-[12.5px] text-slate-400 dark:text-slate-500 hover:border-slate-300 dark:hover:border-slate-600 transition-colors"
          >
            <Search size={14} />
            <span className="flex-1 text-left">Search…</span>
            <kbd className="text-[10px] border border-slate-300 dark:border-slate-600 rounded px-1.5 py-0.5 text-slate-400 dark:text-slate-500">⌘K</kbd>
          </button>
        </div>

        <nav className="flex-1 px-3 py-1 space-y-0.5 overflow-y-auto">
          <NavGroup items={mainNav} />
          <NavGroup title="Forecasts" items={forecastNav as typeof mainNav} />
          <NavGroup title="Tools" items={toolsNav} />
        </nav>

        <div className="px-4 py-4 border-t border-slate-200 dark:border-slate-800 text-[11px] text-slate-400 dark:text-slate-500 space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Eye size={12} />
            <span className="truncate">{env?.database ?? "…"}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${env?.is_qa ? "bg-amber-500" : "bg-emerald-500"} pulse-dot`} />
            <span className="uppercase tracking-wider font-semibold text-slate-500 dark:text-slate-400">
              {env ? (env.is_qa ? "QA environment" : "Production") : "connecting…"}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex-1 min-w-0 flex flex-col">
        <Topbar pageTitle={pageTitle} theme={theme} onToggleTheme={toggle} onOpenPalette={() => setPaletteOpen(true)} />
        <main className="flex-1 min-w-0 overflow-y-auto px-8 py-7">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}

function Topbar({
  pageTitle,
  theme,
  onToggleTheme,
  onOpenPalette,
}: {
  pageTitle: string;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  onOpenPalette: () => void;
}) {
  const { data } = useQuery({
    queryKey: ["health-clock"],
    queryFn: api.health,
    refetchInterval: 30_000,
  });

  return (
    <header className="h-14 shrink-0 border-b border-slate-200 dark:border-slate-800 px-8 flex items-center justify-between bg-white dark:bg-[#0e1420] transition-colors">
      <div className="flex items-center gap-3 text-[13px] text-slate-500 dark:text-slate-400">
        <div className="flex items-center gap-1.5">
          <Activity size={14} className={data ? "text-emerald-500" : "text-slate-300 dark:text-slate-600"} />
          <span>{data ? "API connected" : "connecting to API…"}</span>
        </div>
        {pageTitle && (
          <>
            <ChevronRight size={13} className="text-slate-300 dark:text-slate-700" />
            <span className="font-medium text-slate-700 dark:text-slate-200">{pageTitle}</span>
          </>
        )}
      </div>
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenPalette}
          className="hidden sm:flex items-center gap-1.5 text-[11.5px] text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
        >
          <Search size={13} />
          <kbd className="text-[10px] border border-slate-200 dark:border-slate-700 rounded px-1.5 py-0.5">⌘K</kbd>
        </button>
        <button
          onClick={onToggleTheme}
          aria-label="Toggle theme"
          className="h-8 w-8 rounded-lg flex items-center justify-center text-slate-400 dark:text-slate-500 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        <div className="text-[12px] text-slate-400 dark:text-slate-500 mono">
          {new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
        </div>
      </div>
    </header>
  );
}
