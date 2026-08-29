// Shared commerce pieces (frontend/DESIGN.md). State reads WITHOUT colour:
// glyph + word, always. Money is tabular mono. Motion budget: the mandate
// meter's width transition only.

import { useEffect, useRef, useState } from 'react';
import { purchaseStreamUrl } from '../api';
import { formatMoney } from '../format';
import type { CartView, CommerceSnapshot, CommerceTraceEvent, MandateView, PurchaseResult } from '../types';

// ---------------------------------------------------------------- stamps
const STAMP: Record<string, { glyph: string; word: string; cls: string }> = {
  ACTIVE: { glyph: '●', word: 'set aside', cls: 'stamp-await' },
  RESERVING: { glyph: '◔', word: 'reserving', cls: 'stamp-escalate' },
  COMMITTED: { glyph: '✓', word: 'committed', cls: 'stamp-allow' },
  BLOCKED: { glyph: '✕', word: 'blocked', cls: 'stamp-deny' },
  EXHAUSTED: { glyph: '○', word: 'exhausted', cls: 'stamp-muted' },
  EXPIRED: { glyph: '○', word: 'expired', cls: 'stamp-muted' },
  REVOKED: { glyph: '○', word: 'revoked', cls: 'stamp-muted' },
};

export function StateStamp({ state, word }: { state: string; word?: string }) {
  const s = STAMP[state] ?? { glyph: '·', word: state.toLowerCase(), cls: 'stamp-muted' };
  return (
    <span className={`commerce-stamp ${s.cls}`}>
      <span aria-hidden="true">{s.glyph}</span> {word ?? s.word}
    </span>
  );
}

// Persistent real-vs-modelled provenance chips (09-UI §5): honest, not buried.
export function ClaimChip({ kind }: { kind: 'modelled' | 'real' }) {
  return kind === 'modelled' ? (
    <span className="claim-chip claim-modelled" title="A faithful model over real primitives — not a Razorpay API">
      ▢ modelled
    </span>
  ) : (
    <span className="claim-chip claim-real" title="A real Razorpay test-mode entity">
      ◆ Razorpay · test
    </span>
  );
}

// ---------------------------------------------------------------- the meter
// THE one animated element: money being consumed (or returning on reversal).
export function MandateMeter({ mandate }: { mandate: MandateView | null }) {
  if (!mandate) {
    return (
      <div className="mandate-meter mandate-empty">
        <p>No mandate yet — set one aside to let the agent shop.</p>
      </div>
    );
  }
  const pct = Math.max(0, Math.min(100, (mandate.remaining_minor / mandate.locked_minor) * 100));
  const dead = mandate.status !== 'ACTIVE';
  return (
    <div className="mandate-meter" aria-live="polite">
      <div className="mandate-meter-head">
        <span className="mono muted">{mandate.mandate_id}</span>
        <ClaimChip kind="modelled" />
        <StateStamp state={mandate.status} />
      </div>
      <div className="mandate-amount mono">
        {formatMoney(mandate.remaining_minor, mandate.currency)}
        <span className="mandate-of"> remaining of {formatMoney(mandate.locked_minor, mandate.currency)}</span>
      </div>
      <div className="mandate-bar" role="img"
        aria-label={`${formatMoney(mandate.remaining_minor, mandate.currency)} remaining of ${formatMoney(mandate.locked_minor, mandate.currency)}`}>
        <div className={`mandate-fill${dead ? ' mandate-dead' : ''}`} style={{ width: `${pct}%` }} />
      </div>
      {mandate.reserved_minor > 0 && (
        <p className="muted small">
          <StateStamp state="RESERVING" /> {formatMoney(mandate.reserved_minor, mandate.currency)} on hold
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- the cart
export function CartPanel({ cart }: { cart: CartView | null }) {
  if (!cart || cart.lines.length === 0) {
    return (
      <div className="commerce-panel">
        <div className="panel-head">
          <h3>Cart</h3>
          <ClaimChip kind="modelled" />
        </div>
        <p className="muted">Empty — the agent adds items as it shops. Every price is server-computed.</p>
      </div>
    );
  }
  return (
    <div className="commerce-panel">
      <div className="panel-head">
        <h3>Cart <span className="mono muted">{cart.cart_id}</span></h3>
        <span className="muted small">server-priced · catalog v{cart.catalog_version}</span>
        <ClaimChip kind="modelled" />
      </div>
      <table className="cart-table">
        <tbody>
          {cart.lines.map((ln) => (
            <tr key={ln.item_id}>
              <td>
                {ln.name}
                {ln.upsell_rule_id && (
                  <span className="upsell-mark" title={`Offered by merchant rule ${ln.upsell_rule_id}, explicitly accepted`}>
                    ↖ merchant offer
                  </span>
                )}
              </td>
              <td className="mono">×{ln.quantity}</td>
              <td className="mono">{formatMoney(ln.line_total_minor)}</td>
              <td className="mono muted">+{formatMoney(ln.tax_minor)} tax</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>Total</td>
            <td />
            <td className="mono cart-total" colSpan={2}>{formatMoney(cart.total_minor)}</td>
          </tr>
        </tfoot>
      </table>
      {cart.upsell_offers.length > 0 && (
        <p className="muted small">
          Merchant offer available: {cart.upsell_offers[0].name ?? cart.upsell_offers[0].item_id} at{' '}
          <span className="mono">{formatMoney(cart.upsell_offers[0].offer_total_minor)}</span> — the agent
          decides against your budget; it is never added silently.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- narration
// Left-pane words, derived from the SAME events that drive the machinery —
// written from the user's side (DESIGN.md §5).
export function narrate(evt: CommerceTraceEvent, prev: CommerceSnapshot | null): string | null {
  const p = evt.payload as Record<string, string>;
  if (evt.type === 'run_started') return 'Reading your request…';
  if (evt.type === 'tool_call_forwarded') {
    const tool = String(p.tool ?? '');
    if (tool === 'catalog_search') return 'Reading the catalog — merchant text stays quarantined as data.';
    if (tool === 'cart_create') return 'Opening a cart against your mandate. Thinking is free; only commit binds.';
    if (tool === 'cart_add_item') {
      const before = prev?.cart?.lines?.map((l) => l.item_id) ?? [];
      const after = evt.commerce.cart?.lines ?? [];
      const added = after.find((l) => !before.includes(l.item_id));
      return added ? `Adding ${added.name} ×${added.quantity} — the server prices it.` : 'Adjusting the cart…';
    }
    if (tool === 'cart_remove_item') return 'Removing a line to stay inside your budget.';
    if (tool === 'cart_accept_upsell') return "Accepting the merchant's offer — it fits your budget.";
    if (tool === 'cart_commit') return 'Committing — the server re-prices everything at this moment.';
    if (tool === 'initiate_payment') return 'Paying — inside the consent you gave upfront.';
    if (tool === 'submit_otp') return 'Confirming the payment.';
    if (tool === 'fetch_order_payments') return 'The outcome was unclear — reconciling before anything is retried.';
    return null;
  }
  if (evt.type === 'quarantine_applied') return null;
  if (evt.type === 'policy_decision' && String(p.disposition) === 'DENY') {
    return String(p.human_reason ?? 'Blocked by policy.');
  }
  return null;
}

// ---------------------------------------------------------------- event rows
export function EventRow({ evt }: { evt: CommerceTraceEvent }) {
  const p = evt.payload as Record<string, string>;
  if (evt.type === 'policy_decision') {
    const disp = String(p.disposition ?? '');
    const state = disp === 'ALLOW' ? 'COMMITTED' : disp === 'DENY' ? 'BLOCKED' : 'RESERVING';
    return (
      <div className="event-row">
        <StateStamp state={state} word={disp === 'ALLOW' ? 'policy allowed' : disp === 'DENY' ? 'policy blocked' : 'needs review'} />
        <span className="event-words">{String(p.human_reason ?? '')}</span>
        <span className="mono muted small">{String(p.reason_code ?? '')}</span>
      </div>
    );
  }
  if (evt.type === 'tool_result_received' && String(p.tool) === 'cart_commit' && evt.commerce.commit) {
    return <TwoVerdictRow snapshot={evt.commerce} />;
  }
  if (evt.type === 'quarantine_applied') {
    return (
      <div className="event-row">
        <StateStamp state="RESERVING" word="quarantined" />
        <span className="event-words">Merchant text wrapped as data — instructions inside it are never obeyed.</span>
      </div>
    );
  }
  return null;
}

// One event, two verdicts, both true (ADR-032/033): policy permitted the
// call; commerce ruled on the outcome. Side by side, never merged, never
// hidden — this row IS the architecture.
export function TwoVerdictRow({ snapshot }: { snapshot: CommerceSnapshot }) {
  const commit = snapshot.commit!;
  const refused = commit.commerce !== null && !String(commit.commerce).startsWith('COMMITTED');
  return (
    <div className="two-verdicts">
      <div className="verdict">
        <StateStamp state={commit.policy.disposition === 'ALLOW' ? 'COMMITTED' : 'BLOCKED'}
          word={`policy ${commit.policy.disposition === 'ALLOW' ? 'allowed' : 'blocked'}`} />
        <span className="event-words small">{commit.policy.human_reason}</span>
      </div>
      <div className="verdict">
        <StateStamp state={refused ? 'BLOCKED' : 'COMMITTED'}
          word={`commerce ${refused ? 'refused' : 'committed'}`} />
        <span className="mono small">{commit.commerce}</span>
        {commit.order_id && (
          <span className="small">
            → <span className="mono">{commit.order_id}</span> <ClaimChip kind="real" />
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- stream hook
export type CommerceStreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export function useCommerceStream(runRef: string | null): {
  events: CommerceTraceEvent[];
  result: PurchaseResult | null;
  status: CommerceStreamStatus;
} {
  const [events, setEvents] = useState<CommerceTraceEvent[]>([]);
  const [result, setResult] = useState<PurchaseResult | null>(null);
  const [status, setStatus] = useState<CommerceStreamStatus>('idle');
  const seen = useRef<Set<number>>(new Set());

  useEffect(() => {
    if (!runRef) {
      setEvents([]);
      setResult(null);
      setStatus('idle');
      seen.current = new Set();
      return;
    }
    setEvents([]);
    setResult(null);
    seen.current = new Set();
    setStatus('streaming');
    const es = new EventSource(purchaseStreamUrl(runRef));
    es.addEventListener('trace', (e) => {
      const evt = JSON.parse((e as MessageEvent).data) as CommerceTraceEvent;
      if (seen.current.has(evt.sequence)) return;
      seen.current.add(evt.sequence);
      setEvents((prior) => [...prior, evt]);
    });
    es.addEventListener('done', (e) => {
      setResult(JSON.parse((e as MessageEvent).data) as PurchaseResult);
      setStatus('done');
      es.close();
    });
    es.onerror = () => {
      setStatus((s) => (s === 'done' ? s : 'error'));
      es.close();
    };
    return () => es.close();
  }, [runRef]);

  return { events, result, status };
}
