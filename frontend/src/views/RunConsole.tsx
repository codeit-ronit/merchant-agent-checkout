import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { PolicyDecisionPayload, Scenario, TraceEvent } from '../types';
import { useAsync } from '../useAsync';
import { useRunStream } from '../useRunStream';
import { DecisionChip, toDecisionState } from '../components/DecisionChip';
import { QuarantineBlock, renderWithQuarantine } from '../components/Quarantine';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateBlocks';
import { formatElapsed, formatTimeOfDay, titleCase } from '../format';

export function RunConsole() {
  const scenarios = useAsync<Scenario[]>(() => api.scenarios(), []);
  const [selected, setSelected] = useState<string>('');
  const [autoApprove, setAutoApprove] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [seed, setSeed] = useState<TraceEvent[] | undefined>(undefined);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [suspendedApproval, setSuspendedApproval] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && scenarios.data && scenarios.data.length) {
      // Default to the injected-refund scenario — the money shot.
      const injected = scenarios.data.find((s) => s.id === 'reconcile_injected');
      setSelected(injected ? injected.id : scenarios.data[0].id);
    }
  }, [scenarios.data, selected]);

  const stream = useRunStream(runId, seed);

  const start = useCallback(async () => {
    if (!selected) return;
    setStarting(true);
    setStartError(null);
    setSuspendedApproval(null);
    try {
      const res = await api.createRun(selected, autoApprove);
      setSeed(res.trace);
      setSuspendedApproval(res.suspended_approval);
      setRunId(res.record.id);
    } catch (e) {
      setStartError(
        e instanceof Error ? e.message : 'The run did not start. Start the demo and try again.'
      );
    } finally {
      setStarting(false);
    }
  }, [selected, autoApprove]);

  const selectedLabel = scenarios.data?.find((s) => s.id === selected)?.label ?? '';

  return (
    <div className="view view-run">
      <PageHeader
        title="Run console"
        lede="Watch an agent work a task, one authorized step at a time. The policy decision is the point of every step — allowed, blocked, or escalated for a human."
      />

      <div className="run-controls panel">
        <div className="run-controls-row">
          <label className="field">
            <span className="field-label">Scenario</span>
            <select
              className="select"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={scenarios.loading || !!scenarios.error}
            >
              {scenarios.data?.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field field-inline">
            <input
              type="checkbox"
              checked={autoApprove}
              onChange={(e) => setAutoApprove(e.target.checked)}
            />
            <span className="field-label">
              Auto-authorize escalations
              <small>off = the run suspends and waits in the approval queue</small>
            </span>
          </label>

          <button
            type="button"
            className="btn btn-primary run-btn"
            onClick={start}
            disabled={!selected || starting || stream.status === 'streaming'}
          >
            {starting || stream.status === 'streaming' ? 'Running…' : 'Run'}
          </button>
        </div>
        {startError ? <p className="inline-error">{startError}</p> : null}
      </div>

      {scenarios.loading ? <LoadingState label="Loading scenarios…" /> : null}
      {scenarios.error ? <ErrorState error={scenarios.error} onRetry={scenarios.reload} /> : null}

      {!runId && !scenarios.loading && !scenarios.error ? (
        <EmptyState
          title="No run yet"
          detail="Pick a scenario and press Run. The reconciliation-with-injected-refund scenario shows the control plane block a money-moving call the agent was tricked into requesting."
        />
      ) : null}

      {runId ? (
        <RunTrace
          runId={runId}
          label={selectedLabel}
          events={stream.events}
          status={stream.status}
          onReconnect={stream.reconnect}
          suspendedApproval={suspendedApproval}
        />
      ) : null}
    </div>
  );
}

function useLiveElapsed(events: TraceEvent[], streaming: boolean): number {
  const [now, setNow] = useState<number>(() => Date.now());
  const startWallRef = useRef<number | null>(null);

  useEffect(() => {
    if (streaming && startWallRef.current === null) startWallRef.current = Date.now();
    if (!streaming) return;
    const id = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(id);
  }, [streaming]);

  if (!events.length) return 0;
  if (streaming && startWallRef.current !== null) return now - startWallRef.current;
  // Completed: elapsed is the trace's own span.
  return events[events.length - 1].timestamp_ms - events[0].timestamp_ms;
}

function RunTrace({
  runId,
  label,
  events,
  status,
  onReconnect,
  suspendedApproval,
}: {
  runId: string;
  label: string;
  events: TraceEvent[];
  status: string;
  onReconnect: () => void;
  suspendedApproval: string | null;
}) {
  const streaming = status === 'streaming';
  const elapsed = useLiveElapsed(events, streaming);
  const decisionCount = events.filter((e) => e.type === 'policy_decision').length;
  const denials = events.filter(
    (e) => e.type === 'policy_decision' && (e.payload as unknown as PolicyDecisionPayload).disposition === 'DENY'
  ).length;
  const escalations = events.filter(
    (e) =>
      e.type === 'policy_decision' &&
      (e.payload as unknown as PolicyDecisionPayload).disposition === 'REQUIRE_APPROVAL'
  ).length;

  return (
    <div className="run-trace">
      <div className="run-status-bar panel">
        <div className="run-status-main">
          <span className={`run-dot run-dot--${status}`} aria-hidden="true" />
          <div>
            <div className="run-status-label">{label}</div>
            <div className="run-id mono">{runId}</div>
          </div>
        </div>
        <div className="run-metrics">
          <Metric label="Elapsed" value={formatElapsed(elapsed)} mono />
          <Metric label="Decisions" value={String(decisionCount)} />
          <Metric label="Blocked" value={String(denials)} tone={denials ? 'deny' : undefined} />
          <Metric
            label="Escalated"
            value={String(escalations)}
            tone={escalations ? 'escalate' : undefined}
          />
          <span className="run-live-tag">
            {status === 'streaming'
              ? 'STREAMING'
              : status === 'done'
                ? 'COMPLETE'
                : status === 'error'
                  ? 'STREAM LOST'
                  : ''}
          </span>
        </div>
        {status === 'error' ? (
          <button type="button" className="btn btn-ghost" onClick={onReconnect}>
            Reconnect stream
          </button>
        ) : null}
      </div>

      {suspendedApproval ? (
        <div className="run-suspend-banner" role="note">
          <span className="chip-glyph" aria-hidden="true">
            ⏱
          </span>
          <div>
            <strong>Run suspended — waiting on a human decision.</strong>
            <div>
              A money-moving step needs authorization. It is now in the{' '}
              <a href="#/approvals">approval queue</a> as{' '}
              <span className="mono">{suspendedApproval}</span>.
            </div>
          </div>
        </div>
      ) : null}

      <ol className="trace-list">
        {events.map((e) => (
          <TraceRow key={`${e.sequence}`} event={e} />
        ))}
      </ol>

      {status === 'streaming' ? (
        <div className="trace-pending" aria-live="polite">
          <span className="state-spinner" aria-hidden="true" /> waiting for the next authorized step…
        </div>
      ) : null}
    </div>
  );
}

function Metric({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: 'deny' | 'escalate';
}) {
  return (
    <div className={`metric${tone ? ` metric--${tone}` : ''}`}>
      <span className="metric-label">{label}</span>
      <span className={`metric-value${mono ? ' mono' : ''}`}>{value}</span>
    </div>
  );
}

// --- per-event presentation -------------------------------------------------

function TraceRow({ event }: { event: TraceEvent }) {
  if (event.type === 'policy_decision') {
    return <PolicyDecisionRow event={event} />;
  }
  if (event.type === 'quarantine_applied') {
    const fields = (event.payload as { fields?: string[] }).fields ?? [];
    return (
      <li className="trace-row trace-row--quarantine">
        <TraceGutter event={event} />
        <QuarantineBlock fields={fields} />
      </li>
    );
  }
  return (
    <li className={`trace-row trace-row--${event.type.replace(/_/g, '-')}`}>
      <TraceGutter event={event} />
      <div className="trace-body">
        <div className="trace-headline">
          <span className="trace-type">{titleCase(event.type)}</span>
        </div>
        <div className="trace-detail">{describe(event)}</div>
      </div>
    </li>
  );
}

function TraceGutter({ event }: { event: TraceEvent }) {
  return (
    <div className="trace-gutter">
      <span className="trace-seq mono">#{event.sequence}</span>
      <span className="trace-time mono">{formatTimeOfDay(event.timestamp_ms)}</span>
    </div>
  );
}

function PolicyDecisionRow({ event }: { event: TraceEvent }) {
  const p = event.payload as unknown as PolicyDecisionPayload;
  const [open, setOpen] = useState(p.disposition !== 'ALLOW');
  const state = toDecisionState(p.disposition);
  return (
    <li className={`trace-row trace-row--decision decision-${state.toLowerCase()}`}>
      <TraceGutter event={event} />
      <div className="decision-card">
        <div className="decision-card-top">
          <DecisionChip state={state} size="lg" />
          <code className="reason-code mono">{p.reason_code}</code>
        </div>
        <p className="decision-reason">{renderWithQuarantine(p.human_reason)}</p>
        <button
          type="button"
          className="disclosure-toggle"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
        >
          {open ? '▾' : '▸'} {p.matched_rules.length} matched rule
          {p.matched_rules.length === 1 ? '' : 's'}
          {p.deciding_rule ? ` · deciding: ${p.deciding_rule}` : ''}
        </button>
        {open ? (
          <div className="matched-rules">
            {p.matched_rules.length ? (
              <ul>
                {p.matched_rules.map((r) => (
                  <li key={r} className="mono">
                    {r}
                    {p.deciding_rule === r ? <span className="deciding-tag">deciding</span> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="matched-rules-empty">
                No rule matched — the fail-closed default denied this call.
              </p>
            )}
          </div>
        ) : null}
      </div>
    </li>
  );
}

function describe(event: TraceEvent): React.ReactNode {
  const p = event.payload as Record<string, unknown>;
  switch (event.type) {
    case 'run_started':
      return 'The run opened. Every step from here is recorded to the audit ledger.';
    case 'step_started':
      return 'The agent began a new step.';
    case 'model_reasoning':
      return (
        <span>
          The agent reasoned privately.{' '}
          <span className="muted">
            ({String(p.text_len ?? '?')} characters — content not surfaced)
          </span>
        </span>
      );
    case 'tool_call_requested':
      return (
        <span>
          Requested <code className="mono">{String(p.tool)}</code>
          {p.risk_class ? (
            <span className={`risk-tag risk-${String(p.risk_class).toLowerCase()}`}>
              {titleCase(String(p.risk_class))}
            </span>
          ) : null}
        </span>
      );
    case 'tool_call_forwarded':
      return (
        <span>
          Forwarded to upstream after the decision allowed it
          {p.tool ? (
            <>
              : <code className="mono">{String(p.tool)}</code>
            </>
          ) : null}
          .
        </span>
      );
    case 'tool_result_received':
      return (
        <span>
          Result returned{p.tool ? <> for <code className="mono">{String(p.tool)}</code></> : null}
          {typeof p.redactions === 'number' ? (
            <span className="muted"> · {p.redactions} field(s) redacted before the model saw it</span>
          ) : null}
        </span>
      );
    case 'result_redacted':
      return 'Sensitive fields in the tool result were redacted before returning to the model.';
    case 'run_completed':
      return (
        <span>
          Run complete — {String(p.steps ?? '?')} steps, {String(p.tool_calls ?? '?')} tool calls.
        </span>
      );
    case 'run_suspended':
      return 'Run suspended, awaiting a human authorization.';
    case 'run_resumed':
      return 'Run resumed after an approval was granted.';
    case 'run_failed':
      return 'Run failed and was closed out. Fail-closed: nothing was forwarded on the failing path.';
    case 'run_aborted':
      return 'Run aborted.';
    case 'security_event':
      return renderWithQuarantine(JSON.stringify(p));
    default:
      return <code className="mono muted">{JSON.stringify(p)}</code>;
  }
}
