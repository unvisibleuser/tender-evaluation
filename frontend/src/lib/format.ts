// Display helpers. Timestamps are stored in UTC; we render explicitly in the tender's timezone.

export function formatDateTime(iso: string | null | undefined, timeZone = "Asia/Kolkata"): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const text = new Intl.DateTimeFormat("en-IN", {
    timeZone,
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(d);
  return `${text} (${timeZone === "Asia/Kolkata" ? "IST" : timeZone})`;
}

/** Group an exact decimal string in Indian notation without converting through binary float. */
export function formatInr(value: string): string {
  const negative = value.startsWith("-");
  const [intPartRaw, frac] = (negative ? value.slice(1) : value).split(".");
  const intPart = intPartRaw ?? "0";
  const last3 = intPart.slice(-3);
  const rest = intPart.slice(0, -3);
  const grouped = rest ? rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3 : last3;
  return `${negative ? "-" : ""}₹ ${grouped}${frac !== undefined ? "." + frac.padEnd(2, "0") : ".00"}`;
}

export function shortHash(h: string | null | undefined): string {
  return h ? `${h.slice(0, 12)}…` : "—";
}

export function humanize(code: string): string {
  return code
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/^\w/, (c) => c.toUpperCase());
}

export const ROLE_LABELS: Record<string, string> = {
  TENDER_ADMIN: "Tender Administrator",
  APPROVER: "Approver / Committee",
  TECHNICAL_EVALUATOR: "Technical Evaluator",
  COMMERCIAL_OFFICER: "Commercial Opening Officer",
  AUDITOR: "Auditor",
};
