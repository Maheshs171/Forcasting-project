import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard, FlaskConical, Settings as SettingsIcon, Microscope,
  Users, Stethoscope, DollarSign, Contact, Search, CornerDownLeft,
} from "lucide-react";

interface Item {
  label: string;
  group: string;
  to: string;
  icon: typeof Users;
  keywords?: string;
}

const ITEMS: Item[] = [
  { label: "Overview", group: "Navigate", to: "/", icon: LayoutDashboard },
  { label: "New Patients", group: "Forecasts", to: "/forecast/patients", icon: Users },
  { label: "Encounters", group: "Forecasts", to: "/forecast/encounters", icon: Stethoscope },
  { label: "Collections", group: "Forecasts", to: "/forecast/collections", icon: DollarSign },
  { label: "Contact Lenses", group: "Forecasts", to: "/forecast/contact_lenses", icon: Contact },
  { label: "Data Explorer", group: "Tools", to: "/explore", icon: Microscope, keywords: "eda outliers seasonality weekly monthly" },
  { label: "Training Pipeline", group: "Tools", to: "/train", icon: FlaskConical, keywords: "backtest predict run model" },
  { label: "Settings", group: "Tools", to: "/settings", icon: SettingsIcon, keywords: "connection database" },
];

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const navigate = useNavigate();

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return ITEMS;
    return ITEMS.filter(
      (i) => i.label.toLowerCase().includes(q) || i.group.toLowerCase().includes(q) || i.keywords?.toLowerCase().includes(q)
    );
  }, [query]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
  }, [open]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!open) return;
      if (e.key === "Escape") {
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => Math.min(i + 1, filtered.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const item = filtered[activeIndex];
        if (item) {
          navigate(item.to);
          onClose();
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered, activeIndex, navigate, onClose]);

  if (!open) return null;

  let lastGroup = "";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh] px-4 fade-in" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-slate-900/40 dark:bg-black/60 backdrop-blur-[2px]" onClick={onClose} />
      <div className="relative w-full max-w-[560px] rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl shadow-slate-900/20 overflow-hidden">
        <div className="flex items-center gap-2.5 px-4 py-3.5 border-b border-slate-100 dark:border-slate-800">
          <Search size={16} className="text-slate-400 shrink-0" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Jump to a page, forecast, or tool…"
            className="flex-1 bg-transparent text-[14px] text-slate-800 dark:text-slate-100 placeholder:text-slate-400 focus:outline-none"
          />
          <kbd className="text-[10.5px] text-slate-400 border border-slate-200 dark:border-slate-700 rounded px-1.5 py-0.5">esc</kbd>
        </div>

        <div className="max-h-[360px] overflow-y-auto py-2">
          {filtered.length === 0 && (
            <div className="px-4 py-8 text-center text-[13px] text-slate-400">No matches</div>
          )}
          {filtered.map((item, i) => {
            const showGroup = item.group !== lastGroup;
            lastGroup = item.group;
            const active = i === activeIndex;
            return (
              <div key={item.to}>
                {showGroup && (
                  <div className="px-4 pt-2.5 pb-1 text-[10.5px] font-semibold uppercase tracking-wider text-slate-400">
                    {item.group}
                  </div>
                )}
                <button
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => {
                    navigate(item.to);
                    onClose();
                  }}
                  className={`w-full flex items-center gap-2.5 px-4 py-2 text-[13px] transition-colors ${
                    active
                      ? "bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-300"
                      : "text-slate-600 dark:text-slate-300"
                  }`}
                >
                  <item.icon size={15} className={active ? "text-indigo-600 dark:text-indigo-400" : "text-slate-400"} />
                  <span className="font-medium">{item.label}</span>
                  {active && <CornerDownLeft size={13} className="ml-auto text-indigo-400" />}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
