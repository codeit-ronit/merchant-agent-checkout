import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { ApprovalRequest } from '../types';
import { useAsync } from '../useAsync';
import { DecisionChip } from '../components/DecisionChip';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateBlocks';
import { countdown, formatClock, formatMoney, titleCase } from '../format';

function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

export function ApprovalQueue() {
  const { data, loading, error, reload } = useAsync<ApprovalRequest[]>(() => api.approvals(), []);
  const now = useNow();

  const pending = (data ?? []).filter((a) => a.status === 'PENDING');

  return (
    <div className="view view-approvals">
      <PageHeader
        title="Approval queue"
        lede="The highest-stakes screen in the system. Each item is one money-moving action a person must authorize. Read the sentence, check the flags, decide."
      >
        <span className="queue-count">
          <span className="queue-count-num mono">{pending.length}</span> awaiting review
        </span>
      </PageHeader>

      {loading ? <LoadingState label="Loading the queue…" /> : null}
      {error ? <ErrorState error={error} onRetry={reload} /> : null}

      {!loading && !error && (data ?? []).length === 0 ? (
        <EmptyState
          title="Nothing is waiting on you"
          detail="When a run reaches a step that moves money, it stops here for authorization. Start the Subscription Recovery scenario in the Run console to raise one."
        />
      ) : null}

      <div className="approval-list">
        {(data ?? []).map((a) => (
          <ApprovalCard key={a.id} approval={a} now={now} onResolved={reload} />
        ))}
      </div>
    </div>
  );
}

function ApprovalCard({
  approval,
  now,
  onResolved,
}: {
  approval: ApprovalRequest;
  now: number;
  onResolved: () => void;
}) {
  const [note, setNote] = useState('');
  const [showJson, setShowJson] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const { label: countdownLabel, expired } = countdown(approval.expires_at_ms, now);
  const isPending = approval.status === 'PENDING';
  const isExpired = approval.status === 'EXPIRED' || (isPending && expired);
  const untrusted = approval.processed_untrusted_content;
  const money = approval.context?.money;
  const actionable = isPending && !expired;

  const resolve = useCallback(
    async (approve: boolean) => {
      // Approval on a run flagged for untrusted content requires a note.
      // Rejection never requires justification.
      if (approve && untrusted && note.trim().length === 0) {
        setErr('A note is required to approve a run that processed untrusted content.');
        return;
      }
      setBusy(true);
      setErr(null);
      try {
        await api.resolveApproval(approval.id, approve, note.trim() || undefined);
        onResolved();
      } catch (e) {
        setErr(e instanceof Error ? e.message : 'That decision did not save. Try again.');
      } finally {
        setBusy(false);
      }
    },
    [approval.id, approve_dep(untrusted, note), onResolved]
  );

  const statusChip = () => {
    if (isExpired) return <span className="status-pill status-expired">Expired</span>;
    if (approval.status === 'APPROVED')
      return <span className="status-pill status-approved">Approved</span>;
    if (approval.status === 'REJECTED')
      return <span className="status-pill status-rejected">Rejected</span>;
    if (approval.status === 'CONSUMED')
      return <span className="status-pill status-consumed">Approved · used once</span>;
    return null;
  };

  return (
    <article
      className={
        'approval-card panel' +
        (isExpired ? ' approval-card--expired' : '') +
        (untrusted && actionable ? ' approval-card--flagged' : '')
      }
      aria-disabled={!actionable}
    >
      <header className="approval-head">
        <DecisionChip state="AWAITING" label="Needs authorization" />
        <div className="approval-head-right">
          {statusChip()}
          <span
            className={
              'approval-countdown mono' + (expired ? ' is-expired' : countdownLabel.endsWith('s left') ? ' is-urgent' : '')
            }
            title={`Expires ${formatClock(approval.expires_at_ms)}`}
          >
            {isExpired ? 'Expired' : `⏱ ${countdownLabel}`}
          </span>
        </div>
      </header>

      {/* The sentence IS the interface. */}
      <p className="approval-sentence">
        Authorize <strong>{approval.context?.tool_name ?? 'this action'}</strong>
        {money ? (
          <>
            {' '}
            for <span className="mono amount">{formatMoney(money.amount_minor, money.currency)}</span>
            {money.counterparty_ref ? (
              <>
                {' '}
                to <span className="mono">{money.counterparty_ref}</span>
              </>
            ) : null}
          </>
        ) : null}
        ?
      </p>
      <p className="approval-summary-raw mono">{approval.summary}</p>

      {untrusted ? (
        <div className="untrusted-flag" role="alert">
          <span className="untrusted-glyph" aria-hidden="true">
            ⚠
          </span>
          <div>
            <strong>This run processed untrusted content.</strong>
            <span> Attacker-influenceable text was in the agent's context. Verify the intent before approving.</span>
          </div>
        </div>
      ) : null}

      {approval.decision ? (
        <div className="approval-reason">
          <span className="approval-reason-label">Why it stopped</span>
          <p>{approval.decision.human_reason}</p>
        </div>
      ) : null}

      <dl className="approval-facts">
        <div>
          <dt>Agent</dt>
          <dd className="mono">{String(approval.context?.agent_id ?? '—')}</dd>
        </div>
        <div>
          <dt>Risk class</dt>
          <dd>{approval.context?.risk_class ? titleCase(String(approval.context.risk_class)) : '—'}</dd>
        </div>
        <div>
          <dt>Run</dt>
          <dd className="mono">{approval.run_id}</dd>
        </div>
        <div>
          <dt>Bound to arguments</dt>
          <dd className="mono" title={approval.argument_hash}>
            {approval.argument_hash.slice(0, 16)}…
          </dd>
        </div>
      </dl>

      <button
        type="button"
        className="disclosure-toggle"
        aria-expanded={showJson}
        onClick={() => setShowJson((s) => !s)}
      >
        {showJson ? '▾' : '▸'} Full request (JSON)
      </button>
      {showJson ? (
        <pre className="approval-json mono">{JSON.stringify(approval.context, null, 2)}</pre>
      ) : null}

      {actionable ? (
        <div className="approval-actions">
          <label className="field approval-note-field">
            <span className="field-label">
              Note {untrusted ? <em className="req">required to approve</em> : <em>(optional)</em>}
            </span>
            <textarea
              className="textarea"
              rows={2}
              value={note}
              placeholder={
                untrusted
                  ? 'State what you verified before approving this flagged run.'
                  : 'Optional context for the record.'
              }
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          {err ? <p className="inline-error">{err}</p> : null}
          <div className="approval-buttons">
            <button
              type="button"
              className="btn btn-deny"
              onClick={() => resolve(false)}
              disabled={busy}
            >
              ✕ Reject
            </button>
            <button
              type="button"
              className="btn btn-approve"
              onClick={() => resolve(true)}
              disabled={busy}
            >
              ✓ Approve
            </button>
          </div>
          <p className="approval-single-use">
            Single-use · bound to these exact arguments · re-validated when the run resumes.
          </p>
        </div>
      ) : isExpired ? (
        <p className="approval-expired-note">
          This authorization window closed before anyone acted. The run stays blocked; re-run to raise a fresh request.
        </p>
      ) : approval.note ? (
        <p className="approval-resolved-note">
          Note on the record: <span className="quote">{approval.note}</span>
        </p>
      ) : null}
    </article>
  );
}

// Keeps the useCallback dependency array honest about the note+flag inputs
// without re-creating the callback on every keystroke unnecessarily.
function approve_dep(untrusted: boolean, note: string): string {
  return `${untrusted ? '1' : '0'}:${note}`;
}
