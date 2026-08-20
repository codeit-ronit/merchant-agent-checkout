import { useMemo, useState } from 'react';
import { api } from '../api';
import type { AuditEntry, AuditVerifyResult, Disposition } from '../types';
import { useAsync } from '../useAsync';
import { DecisionChip, toDecisionState } from '../components/DecisionChip';
import { HashChain, type ChainLink } from '../components/HashChain';
import { ErrorState, LoadingState, PageHeader } from '../components/StateBlocks';
import { AUDIT_SAMPLE } from '../fixtures/auditSample';
import { formatTimeOfDay, shortHash, titleCase } from '../format';

export function AuditViewer() {
  const { data, loading, error, reload } = useAsync<AuditEntry[]>(() => api.audit(), []);

  // The chain visual must render even with no backend — fall back to the
  // embedded sample so the signature element is always present.
  const usingSample = !data || data.length === 0;
  const entries = usingSample ? AUDIT_SAMPLE : data;

  return (
    <div className="view view-audit">
      <PageHeader
        title="Audit ledger"
        lede="Every decision the proxy made, sealed into a hash chain. Each entry commits to the one before it — change any record and the chain breaks at that exact point."
      />

      {loading ? <LoadingState label="Loading the ledger…" /> : null}
      {error ? (
        <div className="audit-offline-note">
          <ErrorState error={error} onRetry={reload} />
          <p className="muted audit-sample-hint">
            Showing an embedded sample below so the chain-of-custody visual still renders.
          </p>
        </div>
      ) : null}

      <VerifyPanel entries={entries} usingSample={usingSample} />

      {!loading ? <LedgerTable entries={entries} usingSample={usingSample} /> : null}
    </div>
  );
}

function toChainLinks(entries: AuditEntry[]): ChainLink[] {
  return entries.map((e) => ({
    sequence: e.sequence,
    entry_hash: e.entry_hash,
    previous_hash: e.previous_hash,
    tool_name: e.tool_name,
    disposition: (e.decision?.disposition as Disposition | undefined) ?? null,
  }));
}

function VerifyPanel({ entries, usingSample }: { entries: AuditEntry[]; usingSample: boolean }) {
  const [verifying, setVerifying] = useState(false);
  const [result, setResult] = useState<AuditVerifyResult | null>(null);
  const [verifyErr, setVerifyErr] = useState<string | null>(null);

  // Local, clearly-labelled visual aid: pretend an entry was altered and show
  // the chain break. This does NOT call the backend and changes no data.
  const [tamperSeq, setTamperSeq] = useState<number | null>(null);

  const links = useMemo(() => toChainLinks(entries), [entries]);
  const breakAt = tamperSeq ?? (result && !result.ok ? result.first_break_sequence : null);

  const verify = async () => {
    setVerifying(true);
    setVerifyErr(null);
    try {
      setResult(await api.auditVerify());
      setTamperSeq(null); // a real verification supersedes the simulation
    } catch (e) {
      setVerifyErr(e instanceof Error ? e.message : 'Verification did not run.');
    } finally {
      setVerifying(false);
    }
  };

  const tamperable = links.map((l) => l.sequence).filter((s) => s > 0);

  return (
    <section className="panel verify-panel">
      <div className="verify-top">
        <div className="verify-action">
          <button
            type="button"
            className="btn btn-primary btn-verify"
            onClick={verify}
            disabled={verifying || usingSample}
            title={usingSample ? 'Connect the control plane to verify the live ledger' : undefined}
          >
            {verifying ? 'Walking the chain…' : 'Verify chain'}
          </button>
          {usingSample ? (
            <span className="verify-sample-note muted">
              Live verification needs the control plane. The sample below demonstrates the visual.
            </span>
          ) : null}
        </div>

        {/* The verification result is the visual anchor of this screen. */}
        <VerifyResult
          result={result}
          tamperSeq={tamperSeq}
          verifyErr={verifyErr}
          entryCount={links.length}
        />
      </div>

      <div className="chain-region">
        <div className="chain-region-head">
          <h2 className="subhead">
            Chain of custody{usingSample ? ' — embedded sample' : ''}
          </h2>
          <div className="tamper-control">
            <label className="field field-inline">
              <span className="field-label">Simulate tamper</span>
              <select
                className="select select-sm"
                value={tamperSeq === null ? '' : String(tamperSeq)}
                onChange={(e) => setTamperSeq(e.target.value === '' ? null : Number(e.target.value))}
              >
                <option value="">off</option>
                {tamperable.map((s) => (
                  <option key={s} value={s}>
                    alter entry #{s}
                  </option>
                ))}
              </select>
            </label>
            <span className="tamper-hint muted">local visual aid — no data is changed</span>
          </div>
        </div>

        <HashChain links={links} breakAt={breakAt} />

        {breakAt !== null ? (
          <p className="chain-break-caption">
            The block at <span className="mono">#{breakAt}</span> no longer matches the hash its
            successor committed to. Every entry from there on is unverifiable — the tampering is
            localized and undeniable.
          </p>
        ) : (
          <p className="chain-intact-caption muted">
            Each block's seal matches the next block's back-reference. The chain is continuous.
          </p>
        )}
      </div>
    </section>
  );
}

function VerifyResult({
  result,
  tamperSeq,
  verifyErr,
  entryCount,
}: {
  result: AuditVerifyResult | null;
  tamperSeq: number | null;
  verifyErr: string | null;
  entryCount: number;
}) {
  if (tamperSeq !== null) {
    return (
      <div className="verify-result verify-result--broken" role="status">
        <span className="verify-glyph" aria-hidden="true">
          ✕
        </span>
        <div>
          <div className="verify-headline">Simulated: BROKEN at #{tamperSeq}</div>
          <div className="verify-sub">
            Local demonstration only. Turn off the tamper simulation, then run a real verification.
          </div>
        </div>
      </div>
    );
  }
  if (verifyErr) {
    return (
      <div className="verify-result verify-result--broken" role="alert">
        <span className="verify-glyph" aria-hidden="true">
          ⚠
        </span>
        <div>
          <div className="verify-headline">Verification did not run</div>
          <div className="verify-sub">{verifyErr}</div>
        </div>
      </div>
    );
  }
  if (!result) {
    return (
      <div className="verify-result verify-result--idle">
        <span className="verify-glyph" aria-hidden="true">
          ⛓
        </span>
        <div>
          <div className="verify-headline">{entryCount} entries, not yet verified</div>
          <div className="verify-sub">
            Walk the chain to confirm nothing has been altered since it was written.
          </div>
        </div>
      </div>
    );
  }
  if (result.ok) {
    return (
      <div className="verify-result verify-result--ok" role="status">
        <span className="verify-glyph" aria-hidden="true">
          ✓
        </span>
        <div>
          <div className="verify-headline">Verified — {result.entry_count} entries, chain intact</div>
          <div className="verify-sub">Every seal matches. The record is trustworthy.</div>
        </div>
      </div>
    );
  }
  return (
    <div className="verify-result verify-result--broken" role="alert">
      <span className="verify-glyph" aria-hidden="true">
        ✕
      </span>
      <div>
        <div className="verify-headline">BROKEN at #{result.first_break_sequence}</div>
        <div className="verify-sub">
          The chain fails at entry {result.first_break_sequence}. Everything after it is
          unverifiable. Investigate before trusting the record.
        </div>
      </div>
    </div>
  );
}

const DISPOSITIONS: (Disposition | 'ALL')[] = ['ALL', 'ALLOW', 'DENY', 'REQUIRE_APPROVAL'];

function LedgerTable({ entries, usingSample }: { entries: AuditEntry[]; usingSample: boolean }) {
  const [disp, setDisp] = useState<Disposition | 'ALL'>('ALL');
  const [tool, setTool] = useState<string>('ALL');

  const tools = useMemo(
    () => ['ALL', ...Array.from(new Set(entries.map((e) => e.tool_name))).sort()],
    [entries]
  );

  const filtered = entries.filter((e) => {
    if (disp !== 'ALL' && e.decision?.disposition !== disp) return false;
    if (tool !== 'ALL' && e.tool_name !== tool) return false;
    return true;
  });

  return (
    <section className="panel ledger-panel">
      <div className="ledger-head">
        <h2 className="panel-title">
          Ledger{usingSample ? ' (sample)' : ''}
          <span className="ledger-count mono"> · {filtered.length} of {entries.length}</span>
        </h2>
        <div className="ledger-filters">
          <label className="field field-inline">
            <span className="field-label">Disposition</span>
            <select
              className="select select-sm"
              value={disp}
              onChange={(e) => setDisp(e.target.value as Disposition | 'ALL')}
            >
              {DISPOSITIONS.map((d) => (
                <option key={d} value={d}>
                  {d === 'ALL' ? 'All' : titleCase(d)}
                </option>
              ))}
            </select>
          </label>
          <label className="field field-inline">
            <span className="field-label">Tool</span>
            <select className="select select-sm" value={tool} onChange={(e) => setTool(e.target.value)}>
              {tools.map((t) => (
                <option key={t} value={t}>
                  {t === 'ALL' ? 'All tools' : t}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="ledger-table-wrap">
        <table className="ledger-table">
          <thead>
            <tr>
              <th className="num">Seq</th>
              <th>Time</th>
              <th>Tool</th>
              <th>Risk</th>
              <th>Decision</th>
              <th>Reason</th>
              <th>Entry hash</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((e) => (
              <tr key={e.entry_id}>
                <td className="num mono">{e.sequence}</td>
                <td className="mono time-cell">{formatTimeOfDay(e.timestamp_ms)}</td>
                <td className="mono">{e.tool_name}</td>
                <td>
                  <span className={`risk-tag risk-${e.risk_class.toLowerCase()}`}>
                    {titleCase(e.risk_class)}
                  </span>
                </td>
                <td>
                  {e.decision ? (
                    <DecisionChip state={toDecisionState(e.decision.disposition)} size="sm" />
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="reason-cell">{e.decision?.human_reason ?? '—'}</td>
                <td className="mono hash-cell" title={e.entry_hash}>
                  {shortHash(e.entry_hash, 8, 4)}
                </td>
              </tr>
            ))}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="ledger-empty">
                  No entries match these filters. Widen the disposition or tool filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
