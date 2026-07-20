export function fmtNumber(v: number | null | undefined, isMoney = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (isMoney) {
    return v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  }
  return Math.round(v).toLocaleString("en-US");
}

export function fmtCompact(v: number | null | undefined, isMoney = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return (isMoney ? "$" : "") + (v / 1_000_000).toFixed(1) + "M";
  if (abs >= 1_000) return (isMoney ? "$" : "") + (v / 1_000).toFixed(1) + "K";
  return fmtNumber(v, isMoney);
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}%`;
}

export function fmtMonthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1, 1);
  return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return "never";
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}
