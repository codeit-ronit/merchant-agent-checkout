// Central typed fetch layer. Everything is same-origin under /api. A failed
// request throws ApiError with a code the UI turns into a definite empty/error
// state — the client never crashes on a dead control plane.

import type {
  ApprovalRequest,
  AuditEntry,
  AuditVerifyResult,
  DryRunResult,
  EvalReport,
  HealthResult,
  LiveReport,
  Policy,
  RedteamReport,
  RunResponse,
  RunSummary,
  Scenario,
} from './types';

export type ApiErrorKind = 'network' | 'http' | 'parse';

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;
  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

// The single copy-string the operator sees when the plane is unreachable.
export const UNREACHABLE_HINT = 'Control plane not reachable — run `make demo`';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    });
  } catch (e) {
    // fetch only rejects on network-level failure — the plane is down.
    throw new ApiError('network', UNREACHABLE_HINT);
  }
  if (!res.ok) {
    throw new ApiError('http', `Request failed (${res.status}) for ${path}`, res.status);
  }
  try {
    return (await res.json()) as T;
  } catch {
    throw new ApiError('parse', `Malformed response from ${path}`);
  }
}

export const api = {
  health: () => request<HealthResult>('/health'),

  scenarios: () => request<Scenario[]>('/scenarios'),

  createRun: (scenario_id: string, auto_approve: boolean) =>
    request<RunResponse>('/runs', {
      method: 'POST',
      body: JSON.stringify({ scenario_id, auto_approve }),
    }),

  listRuns: () => request<RunSummary[]>('/runs'),

  getRun: (id: string) => request<RunResponse>(`/runs/${encodeURIComponent(id)}`),

  policies: () => request<Policy[]>('/policies'),

  policySource: (id: string) =>
    request<{ id: string; source: string }>(`/policies/${encodeURIComponent(id)}/source`),

  dryRun: (candidate_policy_id: string, run_id: string) =>
    request<DryRunResult>('/policies/dry-run', {
      method: 'POST',
      body: JSON.stringify({ candidate_policy_id, run_id }),
    }),

  approvals: () => request<ApprovalRequest[]>('/approvals'),

  resolveApproval: (id: string, approve: boolean, note?: string) =>
    request<ApprovalRequest>(`/approvals/${encodeURIComponent(id)}`, {
      method: 'POST',
      body: JSON.stringify({ approve, note: note ?? null }),
    }),

  audit: () => request<AuditEntry[]>('/audit'),

  auditVerify: () => request<AuditVerifyResult>('/audit/verify'),

  evals: () => request<EvalReport>('/evals'),

  redteam: () => request<RedteamReport>('/redteam'),

  live: () => request<LiveReport>('/live'),
};

// Build the SSE stream URL for a run. The Run console tracks the last sequence
// so a reconnect can drop events it has already rendered (backfill without gaps).
export function runStreamUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/stream`;
}

// ---------------------------------------------------------------- commerce
import type {
  CatalogItemView,
  CommerceOrder,
  MandateView,
  PurchaseResult,
} from './types';

export function getCommerceCatalog(): Promise<{
  merchant: { merchant_id: string; display_name: string };
  items: CatalogItemView[];
  catalog_version: number;
  rules: { rule_id: string; trigger_item_id: string; offer_item_id: string }[];
}> {
  return request('/commerce/catalog');
}

export function listMandates(): Promise<MandateView[]> {
  return request('/commerce/mandates');
}

export function createMandate(amountMinor: number, expiresInDays = 7): Promise<MandateView> {
  return request('/commerce/mandates', {
    method: 'POST',
    body: JSON.stringify({ amount_minor: amountMinor, expires_in_days: expiresInDays }),
  });
}

export function revokeMandate(mandateId: string): Promise<MandateView> {
  return request(`/commerce/mandates/${mandateId}/revoke`, { method: 'POST' });
}

export function startPurchase(req: {
  task: string;
  mandate_id: string;
  decline_demo?: boolean;
  timeout_demo?: boolean;
  reprice_demo?: boolean;
}): Promise<PurchaseResult> {
  return request('/commerce/purchase', { method: 'POST', body: JSON.stringify(req) });
}

export function purchaseStreamUrl(runRef: string): string {
  return `/api/commerce/purchase/${runRef}/stream`;
}

export function listCommerceOrders(): Promise<CommerceOrder[]> {
  return request('/commerce/orders');
}

export interface OnboardResult {
  imported: number;
  source: string;
  skipped: string[];
  catalog_version: number;
  items: { item_id: string; name: string; price_minor: number }[];
}

// Not routed through request(): the server's error strings are actionable
// ("looked for JSON-LD/microdata/OG; the CSV path works regardless") and the
// merchant must see them verbatim, not a generic status line.
export async function onboardStorefront(url: string): Promise<OnboardResult> {
  let res: Response;
  try {
    res = await fetch('/api/commerce/onboard', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
  } catch {
    throw new ApiError('network', UNREACHABLE_HINT);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError('http', (body as { error?: string } | null)?.error
      ?? `Request failed (${res.status})`, res.status);
  }
  return body as OnboardResult;
}

export interface RevenueView {
  orders_placed: number;
  orders_captured: number;
  payments_declined: number;
  gross_captured_minor: number;
  upsell_attributed_minor: number;
  aov_minor: number;
  note: string;
}

export function getAgentRevenue(): Promise<RevenueView> {
  return request('/commerce/revenue');
}
