// Formatting helpers. Money is integer minor units throughout — never a float.
// Amounts and identifiers are rendered in a tabular-figure monospace elsewhere.

const CURRENCY_MINOR: Record<string, number> = { INR: 100, USD: 100, EUR: 100 };
const CURRENCY_SYMBOL: Record<string, string> = { INR: '₹', USD: '$', EUR: '€' };

// Format integer minor units as a grouped major-unit amount. INR uses the
// Indian grouping (1,00,000) via Intl; we keep two fraction digits always.
export function formatMoney(amountMinor: number, currency = 'INR'): string {
  const minor = CURRENCY_MINOR[currency] ?? 100;
  const symbol = CURRENCY_SYMBOL[currency] ?? '';
  const major = amountMinor / minor;
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  const body = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(major);
  return `${symbol}${body}`;
}

// Truncate a hash for display: first 8 … last 6. The full value is available
// on hover (title) and in the audit row detail.
export function shortHash(hash: string, head = 10, tail = 6): string {
  if (!hash) return '—';
  if (hash.length <= head + tail + 1) return hash;
  return `${hash.slice(0, head)}…${hash.slice(-tail)}`;
}

export function formatClock(ms: number): string {
  if (!Number.isFinite(ms)) return '—';
  const d = new Date(ms);
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatTimeOfDay(ms: number): string {
  if (!Number.isFinite(ms)) return '—';
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

// Elapsed as m:ss.d for the run console clock.
export function formatElapsed(ms: number): string {
  const total = Math.max(0, ms);
  const s = Math.floor(total / 1000);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  const tenths = Math.floor((total % 1000) / 100);
  return `${m}:${String(rem).padStart(2, '0')}.${tenths}`;
}

// Countdown to an expiry timestamp, given the current clock. Returns a plain
// label and whether it has expired.
export function countdown(expiresAtMs: number, nowMs: number): { label: string; expired: boolean } {
  const remaining = expiresAtMs - nowMs;
  if (remaining <= 0) return { label: 'Expired', expired: true };
  const s = Math.floor(remaining / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return { label: `${h}h ${m}m left`, expired: false };
  if (m > 0) return { label: `${m}m ${String(sec).padStart(2, '0')}s left`, expired: false };
  return { label: `${sec}s left`, expired: false };
}

export function titleCase(s: string): string {
  return s
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
