import { useEffect, useRef } from "react";
import { TerminalSquare } from "lucide-react";

export default function LogConsole({ lines, height = 340 }: { lines: string[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [lines.length]);

  return (
    <div className="rounded-xl border border-white/10 bg-black/40 overflow-hidden">
      <div className="flex items-center gap-1.5 px-3.5 py-2 border-b border-white/[0.06] bg-white/[0.02]">
        <TerminalSquare size={13} className="text-white/40" />
        <span className="text-[11px] text-white/40 font-mono">run output</span>
        <div className="ml-auto flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-red-500/40" />
          <span className="h-2.5 w-2.5 rounded-full bg-amber-500/40" />
          <span className="h-2.5 w-2.5 rounded-full bg-emerald-500/40" />
        </div>
      </div>
      <div
        ref={ref}
        style={{ height }}
        className="overflow-y-auto px-3.5 py-3 font-mono text-[12px] leading-relaxed text-white/70 space-y-0.5"
      >
        {lines.length === 0 && <div className="text-white/25 italic">Waiting for output…</div>}
        {lines.map((l, i) => (
          <LogLine key={i} text={l} />
        ))}
      </div>
    </div>
  );
}

function LogLine({ text }: { text: string }) {
  let cls = "text-white/60";
  if (/error|traceback|failed/i.test(text)) cls = "text-red-400";
  else if (text.trim().startsWith("!")) cls = "text-amber-300";
  else if (/selected|winner|===/i.test(text)) cls = "text-emerald-300";
  else if (text.trim().startsWith("[") || /backtest/i.test(text)) cls = "text-cyan-300";
  return <div className={`whitespace-pre-wrap ${cls}`}>{text || " "}</div>;
}
