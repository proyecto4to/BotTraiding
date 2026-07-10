/** Display formatting helpers (money, percent, dates). Display only. */

export function fmtMoney(value: number | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

/** Formats a fraction (0.0132 -> "1.32%"). */
export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(value);
}

export function fmtDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** Sign-aware class for PnL values: gains green, losses red, zero neutral. */
export function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0 || Number.isNaN(value)) return "";
  return value > 0 ? "pos" : "neg";
}
