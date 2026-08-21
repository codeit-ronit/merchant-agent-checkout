// Typed shapes for the SENTINEL control-plane API. These mirror the JSON the
// FastAPI service emits (see sentinel/api). The frontend never redacts — every
// value here already crossed the wire pre-redacted.

export type Disposition = 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL';

// The four decision states the operator must distinguish at a glance. AWAITING
// is a UI-only state (an approval that exists but is not yet resolved); the
// policy engine only emits the three Dispositions above.
export type DecisionState = 'ALLOW' | 'DENY' | 'REQUIRE_APPROVAL' | 'AWAITING';

export type ApprovalStatus =
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'EXPIRED'
  | 'CONSUMED';

export type TraceEventType =
  | 'run_started'
  | 'step_started'
  | 'model_reasoning'
  | 'tool_call_requested'
  | 'policy_decision'
  | 'approval_requested'
  | 'approval_resolved'
  | 'tool_call_forwarded'
  | 'tool_result_received'
  | 'result_redacted'
  | 'quarantine_applied'
  | 'idempotent_replay'
  | 'provider_switch'
  | 'layer_disagreement'
  | 'security_event'
  | 'run_completed'
  | 'run_failed'
  | 'run_aborted'
  | 'run_suspended'
  | 'run_resumed';

export interface PolicyDecisionPayload {
  disposition: Disposition;
  reason_code: string;
  human_reason: string;
  matched_rules: string[];
  deciding_rule?: string | null;
}

// TraceEvent.payload is intentionally loose — its shape depends on `type`.
export interface TraceEvent {
  run_id: string;
  sequence: number;
  type: TraceEventType;
  timestamp_ms: number;
  step_id?: string | null;
  call_id?: string | null;
  payload: Record<string, unknown>;
}

export interface RunRecord {
  id: string;
  agent_id: string;
  agent_version?: string;
  operator_id?: string;
  policy_set_id?: string;
  policy_set_version?: string;
  terminal_state: string;
  tool_call_count: number;
  denials_by_reason?: Record<string, number>;
  approvals_requested?: number;
  input_task?: string;
  output?: unknown;
}

export interface RunResponse {
  record: RunRecord;
  trace: TraceEvent[];
  scenario: string;
  label: string;
  suspended_approval: string | null;
}

export interface RunSummary {
  id: string;
  label: string;
  terminal_state: string;
  tool_calls: number;
}

export interface Scenario {
  id: string;
  label: string;
}

export interface PolicyRule {
  id: string;
  type: string;
  description: string;
}

export interface Policy {
  id: string;
  version: string;
  description: string;
  is_permissive_baseline: boolean;
  rules: PolicyRule[];
}

export interface Decision {
  disposition: Disposition;
  reason_code: string;
  human_reason: string;
  matched_rules: string[];
  deciding_rule?: string | null;
}

export interface MoneyContext {
  moves_money?: boolean;
  amount_minor: number;
  currency: string;
  counterparty_ref?: string | null;
  target_entities?: string[];
}

export interface ApprovalContext {
  tool_name: string;
  upstream_tool_name?: string;
  risk_class?: string;
  arguments_redacted?: Record<string, unknown>;
  money?: MoneyContext | null;
  [k: string]: unknown;
}

export interface ApprovalRequest {
  id: string;
  run_id: string;
  call_id: string;
  argument_hash: string;
  summary: string;
  created_at_ms: number;
  expires_at_ms: number;
  processed_untrusted_content: boolean;
  status: ApprovalStatus;
  decision: Decision | null;
  context: ApprovalContext;
  resolver_id?: string | null;
  resolved_at_ms?: number | null;
  note?: string | null;
}

export interface AuditEntry {
  entry_id: string;
  run_id: string;
  sequence: number;
  timestamp_ms: number;
  tool_name: string;
  risk_class: string;
  outcome: string;
  arguments_redacted: Record<string, unknown>;
  argument_hash: string;
  decision: (Decision & { deciding_rule?: string | null }) | null;
  previous_hash: string;
  entry_hash: string;
  latency_ms: number;
  policy_eval_ms: number;
}

export interface AuditVerifyResult {
  ok: boolean;
  entry_count: number;
  first_break_sequence: number | null;
  render: string;
}

export interface DryRunChange {
  tool: string;
  was: string;
  reason?: string;
}

export interface DryRunResult {
  candidate_policy: string;
  run_id: string;
  changes: {
    newly_denied: DryRunChange[];
    newly_escalated: DryRunChange[];
    newly_allowed: DryRunChange[];
    unchanged: number;
  };
}

export interface CategoryScores {
  happy_path: number;
  hard_but_correct: number;
  refusal_correct: number;
  policy_triggering: number;
  adversarial_lite: number;
}

export interface ModelMetrics {
  task_success_rate: number;
  by_category: CategoryScores;
  unauthorized_executions: number;
  pii_leaks: number;
  policy_errors: number;
  malformed_tool_calls: number;
  schema_violations?: number;
  over_refusal_rate: number;
  appropriate_refusal_rate: number;
  wall_ms_p50: number;
  wall_ms_p95: number;
  policy_eval_ms_mean: number;
  high_variance_scenarios: string[];
}

export interface GuardrailOverhead {
  policy_eval_ms_mean: number;
  added_wall_ms: number;
  wall_on_ms?: number;
  wall_off_ms?: number;
  accuracy_delta_note?: string;
  note?: string;
}

export interface EvalReport {
  dataset_version: string;
  scenario_count: number;
  models: { strong: ModelMetrics; weak: ModelMetrics };
  guardrail_overhead: GuardrailOverhead;
  scenarios?: Array<{
    id: string;
    model: string;
    category: string;
    passed: boolean;
  }>;
}

// Real-model recording appendix (evals/results/live-*.json), one per provider.
export interface LiveProvider {
  provider: string;
  resolved_models: Record<string, string>; // tier -> real model id
  scenario_count?: number;
  n_runs?: number;
  models: Record<string, ModelMetrics>;
}

export interface LiveReport {
  providers: LiveProvider[];
}

export type Severity = 'L4' | 'L3' | 'L2' | 'L1' | 'L0';
export type SeverityCounts = Partial<Record<Severity, number>>;

export interface PairedResult {
  id: string;
  class: string;
  vector: string;
  agent: string;
  off: Severity;
  on: Severity;
}

export interface RedteamReport {
  dataset_version?: string;
  attack_payloads?: number;
  benign_payloads?: number;
  attack_success_rate_off_pct: number;
  attack_success_rate_on_pct: number;
  false_positive_rate_pct: number;
  severity_off: SeverityCounts;
  severity_on: SeverityCounts;
  ablation: {
    all_on: SeverityCounts;
    no_redaction: SeverityCounts;
    no_quarantine: SeverityCounts;
    no_control_plane: SeverityCounts;
  };
  paired: PairedResult[];
  by_class: Record<string, { off_success: number; on_success: number; n: number }>;
}

export interface HealthResult {
  status: string;
  mode: string;
  note: string;
}
