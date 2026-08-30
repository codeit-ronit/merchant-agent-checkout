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

// ---------------------------------------------------------------- veg mark
// The FSSAI-style square: green dot = veg, red triangle = non-veg. The mark
// every Indian food app carries — instantly readable, no words needed.
export function VegMark({ veg }: { veg: boolean }) {
  return (
    <span className={veg ? 'veg-mark' : 'nonveg-mark'} role="img"
      aria-label={veg ? 'vegetarian' : 'non-vegetarian'} title={veg ? 'veg' : 'non-veg'} />
  );
}

// ---------------------------------------------------------------- the bill
// The cart as a food-app bill: lines with veg marks, then Item total / GST /
// To Pay. Every number is server-computed; the panel says so on its face.
export function BillPanel({ cart, vegOf }: {
  cart: CartView | null;
  vegOf: (itemId: string) => boolean | undefined;
}) {
  if (!cart || cart.lines.length === 0) {
    return (
      <div className="commerce-panel bill-panel">
        <div className="panel-head">
          <h3>Your order</h3>
          <ClaimChip kind="modelled" />
        </div>
        <p className="muted">🛒 Empty — the agent fills this live as it shops. Every price is server-computed; the agent can’t write one.</p>
      </div>
    );
  }
  return (
    <div className="commerce-panel bill-panel">
      <div className="panel-head">
        <h3>Your order</h3>
        <span className="muted small mono">{cart.cart_id}</span>
        <ClaimChip kind="modelled" />
      </div>
      <ul className="bill-lines">
        {cart.lines.map((ln) => {
          const veg = vegOf(ln.item_id);
          return (
            <li key={ln.item_id} className="bill-line">
              {veg !== undefined && <VegMark veg={veg} />}
              <span className="bill-name">
                {ln.name}
                {ln.upsell_rule_id && (
                  <span className="upsell-mark" title={`Offered by merchant rule ${ln.upsell_rule_id}, explicitly accepted`}>
                    ↖ merchant offer
                  </span>
                )}
              </span>
              <span className="mono muted bill-qty">×{ln.quantity}</span>
              <span className="mono bill-amt">{formatMoney(ln.line_total_minor)}</span>
            </li>
          );
        })}
      </ul>
      <div className="bill-details">
        <div className="bill-row"><span>Item total</span><span className="mono">{formatMoney(cart.subtotal_minor)}</span></div>
        <div className="bill-row"><span>GST</span><span className="mono">{formatMoney(cart.tax_total_minor)}</span></div>
        <div className="bill-row bill-topay"><span>To pay</span><span className="mono">{formatMoney(cart.total_minor)}</span></div>
      </div>
      <p className="muted small bill-foot">server-priced · catalog v{cart.catalog_version} — the agent never computes a price</p>
      {cart.upsell_offers.length > 0 && (
        <div className="offer-card">
          <span className="offer-tag">Complete your meal</span>
          <span>{cart.upsell_offers[0].name ?? cart.upsell_offers[0].item_id}</span>
          <span className="mono">{formatMoney(cart.upsell_offers[0].offer_total_minor)}</span>
          <span className="muted small">the agent decides against your budget — never added silently</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- journey
// The pipeline, made visible: five stages that light up from the SAME event
// stream that drives everything else. No stage is ever inferred from time —
// each one flips on the event that actually happened.
export type JourneyState = 'pending' | 'active' | 'done' | 'warn' | 'fail';
export interface JourneyStage {
  key: string;
  label: string;
  sub: string;
  state: JourneyState;
  real?: boolean; // ◆ Razorpay·test provenance on the order stage
}

const J_GLYPH: Record<JourneyState, string> = {
  pending: '·', active: '◔', done: '✓', warn: '!', fail: '✕',
};

export function JourneyTracker({ stages }: { stages: JourneyStage[] }) {
  return (
    <div className="journey" role="list" aria-label="Order journey — the pipeline, live">
      {stages.map((s, i) => (
        <div key={s.key} role="listitem"
          className={`j-node j-${s.state}`} aria-current={s.state === 'active' ? 'step' : undefined}>
          {i > 0 && <span className={`j-bar ${stages[i - 1].state === 'done' ? 'j-bar-done' : ''}`} aria-hidden="true" />}
          <span className="j-dot" aria-hidden="true">{J_GLYPH[s.state]}</span>
          <span className="j-label">{s.label}{s.real && s.state === 'done' && <span className="j-real" title="A real Razorpay test-mode entity"> ◆</span>}</span>
          <span className="j-sub mono">{s.sub}</span>
        </div>
      ))}
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

// ---------------------------------------------------------------- cx bits
// The demo skin's living pieces: the agent's presence, counted-up stats,
// and the thinking indicator. All honour prefers-reduced-motion.

export function AgentOrb({ active = false, size = 34 }: { active?: boolean; size?: number }) {
  return (
    <span className={`agent-orb${active ? ' orb-active' : ''}`}
      style={{ width: size, height: size }} aria-hidden="true">
      <span className="orb-core" />
    </span>
  );
}

export function Typing() {
  return (
    <span className="typing" aria-label="the agent is working">
      <span /><span /><span />
    </span>
  );
}

export function CountUp({ to, duration = 1100, format }: {
  to: number; duration?: number; format?: (n: number) => string;
}) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setValue(to);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(Math.round(to * eased));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to, duration]);
  return <>{format ? format(value) : value}</>;
}
