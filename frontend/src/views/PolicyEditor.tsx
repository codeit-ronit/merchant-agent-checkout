import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { DryRunResult, Policy, RunSummary } from '../types';
import { useAsync } from '../useAsync';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/StateBlocks';
import { titleCase } from '../format';

export function PolicyEditor() {
  const policies = useAsync<Policy[]>(() => api.policies(), []);
  const [selectedId, setSelectedId] = useState<string>('');

  useEffect(() => {
    if (!selectedId && policies.data && policies.data.length) {
      const strict = policies.data.find((p) => p.id === 'strict');
      setSelectedId(strict ? strict.id : policies.data[0].id);
    }
  }, [policies.data, selectedId]);

  const selected = policies.data?.find((p) => p.id === selectedId);

  return (
    <div className="view view-policies">
      <PageHeader
        title="Policy sets"
        lede="Read the rules the proxy enforces, and dry-run a candidate against a real run before you ship it. Loosening a rule is the change that deserves the most scrutiny."
      />

      {policies.loading ? <LoadingState label="Loading policy sets…" /> : null}
      {policies.error ? <ErrorState error={policies.error} onRetry={policies.reload} /> : null}

      {policies.data ? (
        <div className="policy-layout">
          <aside className="policy-list panel">
            <h2 className="panel-title">Policy sets</h2>
            <ul>
              {policies.data.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    className={
                      'policy-list-item' + (p.id === selectedId ? ' policy-list-item--active' : '')
                    }
                    onClick={() => setSelectedId(p.id)}
                  >
                    <span className="policy-list-name mono">{p.id}</span>
                    <span className="policy-list-ver mono">v{p.version}</span>
                    {p.is_permissive_baseline ? (
                      <span className="baseline-badge">RED-TEAM BASELINE — guardrails off</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <div className="policy-detail">
            {selected ? <PolicyView policy={selected} /> : null}
          </div>
        </div>
      ) : null}

      <DryRunPanel policies={policies.data ?? []} />
    </div>
  );
}

function PolicyView({ policy }: { policy: Policy }) {
  const source = useAsync<{ id: string; source: string }>(
    () => api.policySource(policy.id),
    [policy.id]
  );

  return (
    <div className="panel policy-view">
      <div className="policy-view-head">
        <div>
          <h2 className="policy-view-title mono">{policy.id}</h2>
          <p className="policy-view-desc">{policy.description}</p>
        </div>
        {policy.is_permissive_baseline ? (
          <span className="baseline-badge baseline-badge--lg">
            RED-TEAM BASELINE — guardrails off
          </span>
        ) : null}
      </div>

      <div className="policy-rules">
        <h3 className="subhead">Rules ({policy.rules.length})</h3>
        <ul className="rule-list">
          {policy.rules.map((r) => (
            <li key={r.id} className="rule-item">
              <div className="rule-item-head">
                <span className="rule-id mono">{r.id}</span>
                <span className="rule-type">{titleCase(r.type)}</span>
              </div>
              <p className="rule-desc">{r.description}</p>
            </li>
          ))}
        </ul>
      </div>

      <div className="policy-source">
        <h3 className="subhead">Source (read-only)</h3>
        {source.loading ? <LoadingState label="Loading YAML…" /> : null}
        {source.error ? <ErrorState error={source.error} onRetry={source.reload} /> : null}
        {source.data ? (
          <pre className="yaml mono" aria-label={`YAML source for ${policy.id}`}>
            {source.data.source || '# (no source available)'}
          </pre>
        ) : null}
      </div>
    </div>
  );
}

function DryRunPanel({ policies }: { policies: Policy[] }) {
  const runs = useAsync<RunSummary[]>(() => api.listRuns(), []);
  const [candidate, setCandidate] = useState('');
  const [runId, setRunId] = useState('');
  const [result, setResult] = useState<DryRunResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!candidate && policies.length) setCandidate(policies[0].id);
  }, [policies, candidate]);
  useEffect(() => {
    if (!runId && runs.data && runs.data.length) setRunId(runs.data[0].id);
  }, [runs.data, runId]);

  const simulate = useCallback(async () => {
    if (!candidate || !runId) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      setResult(await api.dryRun(candidate, runId));
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'The dry-run did not complete.');
    } finally {
      setBusy(false);
    }
  }, [candidate, runId]);

  return (
    <section className="panel dry-run-panel">
      <h2 className="panel-title">Dry-run simulator</h2>
      <p className="panel-lede">
        Replay a recorded run's decisions under a different policy set. Every decision that would
        change is listed below — pay closest attention to anything newly allowed.
      </p>

      {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : null}

      {!runs.loading && !runs.error && (runs.data ?? []).length === 0 ? (
        <EmptyState
          title="No recorded runs to simulate against"
          detail="Start a scenario in the Run console first. The dry-run replays that run's real decisions under the candidate policy."
        />
      ) : (
        <>
          <div className="dry-run-controls">
            <label className="field">
              <span className="field-label">Candidate policy</span>
              <select className="select" value={candidate} onChange={(e) => setCandidate(e.target.value)}>
                {policies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.id}
                    {p.is_permissive_baseline ? ' (baseline — guardrails off)' : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field-label">Against run</span>
              <select
                className="select"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                disabled={runs.loading}
              >
                {runs.data?.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label} · {r.id.slice(0, 14)}…
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn btn-primary"
              onClick={simulate}
              disabled={busy || !candidate || !runId}
            >
              {busy ? 'Simulating…' : 'Run dry-run'}
            </button>
          </div>
          {err ? <p className="inline-error">{err}</p> : null}
          {result ? <DryRunResultView result={result} /> : null}
        </>
      )}
    </section>
  );
}

function DryRunResultView({ result }: { result: DryRunResult }) {
  const c = result.changes;
  const noChange =
    c.newly_denied.length === 0 && c.newly_escalated.length === 0 && c.newly_allowed.length === 0;

  return (
    <div className="dry-run-result">
      <div className="dry-run-summary">
        Applying <span className="mono">{result.candidate_policy}</span> to{' '}
        <span className="mono">{result.run_id.slice(0, 18)}…</span> — {c.unchanged} decision
        {c.unchanged === 1 ? '' : 's'} unchanged.
      </div>

      {c.newly_allowed.length > 0 ? (
        <div className="change-group change-group--warn">
          <div className="change-group-head">
            <span className="change-glyph" aria-hidden="true">
              ⚠
            </span>
            <h3>Newly allowed — {c.newly_allowed.length}</h3>
            <span className="change-warn-tag">loosening · review carefully</span>
          </div>
          <p className="change-group-note">
            These calls were previously stopped and would now go through. Loosening policy is the
            change most likely to be made carelessly.
          </p>
          <ul className="change-list">
            {c.newly_allowed.map((ch, i) => (
              <li key={i} className="change-row">
                <code className="mono">{ch.tool}</code>
                <span className="change-was">was {ch.was}</span>
                {ch.reason ? <span className="change-reason">{ch.reason}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="change-grid">
        <ChangeGroup
          title="Newly denied"
          tone="deny"
          glyph="✕"
          changes={c.newly_denied}
          empty="Nothing newly blocked."
        />
        <ChangeGroup
          title="Newly escalated"
          tone="escalate"
          glyph="▲"
          changes={c.newly_escalated}
          empty="Nothing newly escalated."
        />
      </div>

      {noChange ? (
        <p className="dry-run-nochange">
          This candidate would make no decision on this run behave differently.
        </p>
      ) : null}
    </div>
  );
}

function ChangeGroup({
  title,
  tone,
  glyph,
  changes,
  empty,
}: {
  title: string;
  tone: 'deny' | 'escalate';
  glyph: string;
  changes: { tool: string; was: string }[];
  empty: string;
}) {
  return (
    <div className={`change-group change-group--${tone}`}>
      <div className="change-group-head">
        <span className="change-glyph" aria-hidden="true">
          {glyph}
        </span>
        <h3>
          {title} — {changes.length}
        </h3>
      </div>
      {changes.length ? (
        <ul className="change-list">
          {changes.map((ch, i) => (
            <li key={i} className="change-row">
              <code className="mono">{ch.tool}</code>
              <span className="change-was">was {ch.was}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="change-group-empty">{empty}</p>
      )}
    </div>
  );
}
