// The order experience, staged like a product (not accumulated like a
// dashboard). Three phases, one focus each:
//   compose — one card: what do you want, what's the cap, any twist
//   running — the journey bar leads; chat + bill move in the same beat,
//             the menu shelf shows what the agent is picking from
//   done    — the receipt takes center stage
// Everything on screen derives from ONE paced event stream, so no panel can
// ever disagree with another.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { createMandate, getCommerceCatalog, listMandates, startPurchase } from '../api';
import { formatMoney } from '../format';
import type {
  BuyerReport,
  CartView,
  CatalogItemView,
  CommerceSnapshot,
  CommerceTraceEvent,
  MandateView,
  PurchaseResult,
} from '../types';
import {
  BillPanel,
  ClaimChip,
  EventRow,
  JourneyTracker,
  StateStamp,
  Typing,
  VegMark,
  narrate,
  useCommerceStream,
} from '../components/commerce';
import type { JourneyStage } from '../components/commerce';

const DEFAULT_TASK = 'Order dinner for four under ₹800, no beef';

type Twist = 'none' | 'decline' | 'reprice' | 'timeout';
const TWISTS: Array<{ id: Twist; label: string; glyph: string }> = [
  { id: 'none', label: 'Clean run', glyph: '✓' },
  { id: 'decline', label: 'Payment declines', glyph: '💳' },
  { id: 'reprice', label: 'Price changes mid-purchase', glyph: '🏷️' },
  { id: 'timeout', label: 'Rail times out', glyph: '⏱️' },
];

// Emoji tiles for the menu — keyword-mapped, no external images.
const DISH_GLYPHS: Array<[RegExp, string]> = [
  [/beef/i, '🥩'], [/chicken/i, '🍗'], [/dal/i, '🍲'], [/thali/i, '🍱'],
  [/naan|roti/i, '🫓'], [/jamun/i, '🍮'], [/chaas|lassi/i, '🥛'],
  [/paneer/i, '🧆'], [/rice/i, '🍚'], [/biryani/i, '🍛'],
];
function dishGlyph(name: string): string {
  for (const [re, g] of DISH_GLYPHS) if (re.test(name)) return g;
  return '🍽️';
}
const isVeg = (item: CatalogItemView) => item.attributes.includes('veg');

// ---------------------------------------------------------------- journey
// Pure function of the stream — stages flip on events, never on timers.
function deriveJourney(
  events: CommerceTraceEvent[],
  result: PurchaseResult | null,
  streaming: boolean,
  mandate: MandateView | null,
  cart: CartView | null,
): JourneyStage[] {
  const finished = result !== null;
  const decision = result?.output?.decision ?? null;

  const commitForwarded = events.some(
    (e) => e.type === 'tool_call_forwarded' && String(e.payload.tool) === 'cart_commit');
  const reconciling = events.some(
    (e) => e.type === 'tool_call_forwarded' && String(e.payload.tool) === 'fetch_order_payments');
  let latestCommit: CommerceSnapshot['commit'] = null;
  let refusedOnce = false;
  for (const e of events) {
    if (e.commerce.commit) {
      latestCommit = e.commerce.commit;
      if (e.commerce.commit.commerce && !String(e.commerce.commit.commerce).startsWith('COMMITTED')) {
        refusedOnce = true;
      }
    }
  }
  if (!latestCommit && result?.final_snapshot.commit) latestCommit = result.final_snapshot.commit;
  const committedOk = latestCommit?.commerce != null && String(latestCommit.commerce).startsWith('COMMITTED');
  const orderId = latestCommit?.order_id ?? result?.output?.order_id ?? null;
  const payment = (events.length ? events[events.length - 1].commerce.payment : null)
    ?? result?.final_snapshot.payment ?? null;

  const consent: JourneyStage = mandate
    ? { key: 'cap', label: 'Spending cap', state: 'done', sub: `${formatMoney(mandate.locked_minor)} set aside` }
    : { key: 'cap', label: 'Spending cap', state: 'pending', sub: 'set once, revocable' };

  let shop: JourneyStage = { key: 'shop', label: 'Agent shops', state: 'pending', sub: 'free · off the rail' };
  if (streaming && !commitForwarded) {
    shop = { key: 'shop', label: 'Agent shops', state: 'active',
      sub: cart ? `${formatMoney(cart.total_minor)} in cart` : 'reading the menu…' };
  } else if (commitForwarded || finished) {
    if (finished && decision !== 'purchased' && decision !== 'payment_declined' && !commitForwarded) {
      shop = { key: 'shop', label: 'Agent shops', state: 'warn', sub: 'declined honestly' };
    } else {
      shop = { key: 'shop', label: 'Agent shops', state: 'done',
        sub: cart ? `${formatMoney(cart.total_minor)} in cart` : 'cart built' };
    }
  }

  let gate: JourneyStage = { key: 'gate', label: 'Price lock', state: 'pending', sub: 're-price · cap check' };
  if (commitForwarded && !latestCommit) {
    gate = { key: 'gate', label: 'Price lock', state: 'active', sub: 're-pricing…' };
  } else if (committedOk) {
    gate = { key: 'gate', label: 'Price lock', state: 'done',
      sub: refusedOnce ? 'refused once → re-confirmed' : `re-priced ✓ ${cart ? formatMoney(cart.total_minor) : ''}` };
  } else if (refusedOnce) {
    gate = { key: 'gate', label: 'Price lock', state: finished ? 'fail' : 'active',
      sub: 'price changed — refused' };
  }

  const order: JourneyStage = orderId
    ? { key: 'order', label: 'Real order', state: 'done', sub: orderId, real: true }
    : { key: 'order', label: 'Real order', state: committedOk ? 'active' : 'pending', sub: 'Razorpay · test mode' };

  let pay: JourneyStage = { key: 'pay', label: 'Payment', state: 'pending', sub: 'modelled rail' };
  if (payment) {
    if (payment.status === 'captured') {
      pay = { key: 'pay', label: 'Payment', state: 'done', sub: 'paid ✓' };
    } else if (payment.status === 'failed' || decision === 'payment_declined') {
      pay = { key: 'pay', label: 'Payment', state: 'fail', sub: 'declined — money returned' };
    } else {
      pay = { key: 'pay', label: 'Payment', state: 'active', sub: payment.status };
    }
  } else if (decision === 'payment_declined') {
    pay = { key: 'pay', label: 'Payment', state: 'fail', sub: 'declined — money returned' };
  } else if (reconciling) {
    pay = { key: 'pay', label: 'Payment', state: 'active', sub: 'reconciling…' };
  } else if (orderId && streaming) {
    pay = { key: 'pay', label: 'Payment', state: 'active', sub: 'paying…' };
  }

  return [consent, shop, gate, order, pay];
}

// ---------------------------------------------------------------- menu shelf
function MenuShelf({ items, merchantName, cart }: {
  items: CatalogItemView[];
  merchantName: string;
  cart: CartView | null;
}) {
  const inCart = new Map((cart?.lines ?? []).map((l) => [l.item_id, l]));
  return (
    <div className="shelf">
      <div className="shelf-head">
        <h3>On the menu at {merchantName || 'Fresh Basket'}</h3>
        <ClaimChip kind="modelled" />
        <span className="muted small">the agent picks; the server prices</span>
      </div>
      <div className="shelf-row" role="list">
        {items.map((it) => {
          const line = inCart.get(it.item_id);
          const soldOut = it.stock === 'OUT_OF_STOCK';
          return (
            <div key={it.item_id} role="listitem"
              className={`shelf-card${line ? ' shelf-picked' : ''}${soldOut ? ' shelf-out' : ''}`}>
              <span className="shelf-tile" aria-hidden="true">{dishGlyph(it.name)}</span>
              <div className="shelf-info">
                <span className="shelf-name"><VegMark veg={isVeg(it)} /> {it.name}</span>
                <span className="mono shelf-price">{formatMoney(it.price_minor)}</span>
              </div>
              {line && <span className="shelf-badge">×{line.quantity} in cart</span>}
              {soldOut && <span className="shelf-badge shelf-badge-out">sold out</span>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function BuyerConsole() {
  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [mandateId, setMandateId] = useState<string>('');
  const [capRupees, setCapRupees] = useState('2000');
  const [task, setTask] = useState(DEFAULT_TASK);
  const [twist, setTwist] = useState<Twist>('none');
  const [runRef, setRunRef] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState<CatalogItemView[]>([]);
  const [merchantName, setMerchantName] = useState('');
  const { events, result, status } = useCommerceStream(runRef);

  const refreshMandates = useCallback(async () => {
    try {
      const list = await listMandates();
      setMandates(list);
      if (!mandateId && list.length) setMandateId(list[list.length - 1].mandate_id);
    } catch { /* the cap row shows the empty state */ }
  }, [mandateId]);

  useEffect(() => { void refreshMandates(); }, [refreshMandates]);
  useEffect(() => {
    getCommerceCatalog()
      .then((cat) => { setMenu(cat.items); setMerchantName(cat.merchant.display_name); })
      .catch(() => { /* shelf just stays empty; the run still works */ });
  }, []);

  const snapshot: CommerceSnapshot | null = useMemo(() => {
    if (status === 'done' && result) return result.final_snapshot;
    return events.length ? events[events.length - 1].commerce : null;
  }, [events, result, status]);

  const selected = mandates.find((m) => m.mandate_id === mandateId) ?? null;
  const liveMandate = snapshot?.mandate ?? selected;
  const liveCart = snapshot?.cart ?? null;
  const phase: 'compose' | 'running' | 'done' =
    runRef === null ? 'compose' : status === 'done' || status === 'error' ? 'done' : 'running';

  const journey = useMemo(
    () => deriveJourney(events, result, status === 'streaming', liveMandate, liveCart),
    [events, result, status, liveMandate, liveCart]);

  const vegByItem = useMemo(() => new Map(menu.map((it) => [it.item_id, isVeg(it)])), [menu]);

  const narration = useMemo(() => {
    const lines: string[] = [];
    events.forEach((evt, i) => {
      const prev = i > 0 ? events[i - 1].commerce : null;
      const words = narrate(evt, prev);
      if (words && lines[lines.length - 1] !== words) lines.push(words);
    });
    return lines;
  }, [events]);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      let mid = selected?.status === 'ACTIVE' ? selected.mandate_id : '';
      if (!mid) {
        const rupees = Number(capRupees);
        if (!Number.isFinite(rupees) || rupees <= 0) {
          setError('Enter a spending cap in rupees — that one approval is what the agent spends inside.');
          setBusy(false);
          return;
        }
        const m = await createMandate(Math.round(rupees) * 100);
        setMandates((prior) => [...prior, m]);
        setMandateId(m.mandate_id);
        mid = m.mandate_id;
      }
      const res = await startPurchase({
        task,
        mandate_id: mid,
        decline_demo: twist === 'decline',
        timeout_demo: twist === 'timeout',
        reprice_demo: twist === 'reprice',
      });
      setRunRef(res.run_ref);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The order could not start.');
    } finally {
      setBusy(false);
      void refreshMandates();
    }
  }

  function newOrder() {
    setRunRef(null);
    setTwist('none');
    void refreshMandates();
  }

  // ------------------------------------------------------------ compose
  if (phase === 'compose') {
    return (
      <div className="order-page">
        <div className="composer">
          <p className="eyebrow">Live demo · fixture mode · no sign-up, nothing real is charged</p>
          <h1>What should the agent get you?</h1>
          <textarea
            className="composer-task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={2}
            aria-label="What should the agent buy?"
          />
          <div className="cap-row">
            <span className="cap-label">Spending cap</span>
            {selected?.status === 'ACTIVE' ? (
              <span className="cap-chip">
                <StateStamp state="ACTIVE" word="active" />
                <span className="mono">{formatMoney(selected.remaining_minor)}</span> left of{' '}
                <span className="mono">{formatMoney(selected.locked_minor)}</span>
                <span className="muted small mono"> · {selected.mandate_id}</span>
              </span>
            ) : (
              <span className="cap-set">
                <span className="mono cap-rupee">₹</span>
                <input className="cap-input mono" value={capRupees} inputMode="numeric"
                  onChange={(e) => setCapRupees(e.target.value)}
                  aria-label="Spending cap in rupees" />
                <span className="muted small">set aside when you send · revocable anytime</span>
              </span>
            )}
          </div>
          {mandates.length > 0 && (
            <details className="cap-manage">
              <summary className="muted small">manage caps ({mandates.length})</summary>
              <div className="mandate-list">
                {mandates.map((m) => (
                  <label key={m.mandate_id} className="mandate-option">
                    <input type="radio" name="mandate" checked={mandateId === m.mandate_id}
                      onChange={() => setMandateId(m.mandate_id)} />
                    <StateStamp state={m.status} />
                    <span className="mono">{formatMoney(m.remaining_minor)} </span>
                    <span className="muted small mono">{m.mandate_id}</span>
                  </label>
                ))}
              </div>
            </details>
          )}
          <div className="twist-row" role="radiogroup" aria-label="Optional failure story">
            <span className="muted small">Add a twist:</span>
            {TWISTS.map((t) => (
              <button key={t.id} type="button"
                className={`twist-chip${twist === t.id ? ' twist-on' : ''}`}
                aria-pressed={twist === t.id}
                onClick={() => setTwist(t.id)}>
                <span aria-hidden="true">{t.glyph}</span> {t.label}
              </button>
            ))}
          </div>
          <button className="btn-cta composer-send" onClick={() => void send()} disabled={busy}>
            {busy ? 'Starting…' : 'Send the agent shopping →'}
          </button>
          {error && <p className="error-words" role="alert">{error}</p>}
          <p className="muted small composer-foot">
            The shop is modelled with real prices; the order that comes out is a real Razorpay
            test-mode order. <ClaimChip kind="modelled" /> <ClaimChip kind="real" />
          </p>
        </div>
        <MenuShelf items={menu} merchantName={merchantName} cart={null} />
      </div>
    );
  }

  // ------------------------------------------------------------ running/done
  return (
    <div className="order-page">
      <div className="live-bar">
        <span className="live-task">“{task}”</span>
        {twist !== 'none' && (
          <span className="twist-chip twist-on twist-static">
            {TWISTS.find((t) => t.id === twist)?.glyph} {TWISTS.find((t) => t.id === twist)?.label}
          </span>
        )}
        <button className="btn-ghost live-new" onClick={newOrder} disabled={status === 'streaming'}>
          {status === 'streaming' ? 'Order in flight…' : '+ New order'}
        </button>
      </div>

      <JourneyTracker stages={journey} />

      {phase === 'done' && result?.output && (
        <FinalCard report={result.output} snapshot={result.final_snapshot} onNewOrder={newOrder} />
      )}

      <div className="live-grid">
        <section className="chat-panel" aria-label="The agent" aria-live="polite">
          <div className="chat-head">
            <span className={`agent-dot${status === 'streaming' ? ' agent-dot-on' : ''}`} aria-hidden="true" />
            <h3>The agent</h3>
            {status === 'streaming' && <span className="muted small">working…</span>}
          </div>
          <div className="chat-flow">
            <div className="chat-bubble chat-user">{task}</div>
            {narration.map((line, i) => (
              <div key={i} className="chat-bubble chat-agent">{line}</div>
            ))}
            {status === 'streaming' && (
              <div className="chat-bubble chat-agent chat-typing" aria-hidden="true"><Typing /></div>
            )}
          </div>
        </section>

        <section className="side-panel" aria-label="Your order and cap">
          <BillPanel cart={liveCart} vegOf={(id) => vegByItem.get(id)} />
          {liveMandate && (
            <div className="cap-meter">
              <div className="cap-meter-row">
                <span>Spending cap</span>
                <span className="mono">
                  {formatMoney(liveMandate.remaining_minor)} <span className="muted">left of {formatMoney(liveMandate.locked_minor)}</span>
                </span>
              </div>
              <div className="mandate-bar">
                <div className={`mandate-fill${liveMandate.status !== 'ACTIVE' ? ' mandate-dead' : ''}`}
                  style={{ width: `${Math.max(0, Math.min(100, (liveMandate.remaining_minor / liveMandate.locked_minor) * 100))}%` }} />
              </div>
              {liveMandate.reserved_minor > 0 && (
                <p className="muted small"><StateStamp state="RESERVING" /> {formatMoney(liveMandate.reserved_minor)} on hold</p>
              )}
            </div>
          )}
        </section>
      </div>

      <MenuShelf items={menu} merchantName={merchantName} cart={liveCart} />

      <details className="decisions-drawer">
        <summary>Every decision, stamped — for the curious ({events.length} events)</summary>
        <div className="event-feed">
          {events.map((evt) => (
            <EventRow key={evt.sequence} evt={evt} />
          ))}
        </div>
      </details>
    </div>
  );
}

// The receipt / the failure card — designed states, not residue.
function FinalCard({ report, snapshot, onNewOrder }: {
  report: BuyerReport;
  snapshot: CommerceSnapshot;
  onNewOrder: () => void;
}) {
  if (report.decision === 'purchased') {
    return (
      <div className="final-card final-ok receipt2">
        <span className="receipt2-check" aria-hidden="true">✓</span>
        <h3>Order placed</h3>
        <p className="receipt-amount mono">{formatMoney(report.total_minor ?? 0)}</p>
        <p>
          Order <span className="mono">{report.order_id}</span> <ClaimChip kind="real" /> · payment{' '}
          <span className="mono">{report.payment_status}</span> <ClaimChip kind="modelled" />
        </p>
        <p className="muted small">
          {formatMoney(report.mandate_remaining_minor ?? 0)} still protected in your cap ·{' '}
          {report.upsell_accepted ? 'includes a merchant offer, marked in the bill' : 'no extras added'}
        </p>
        <button className="btn-ghost" onClick={onNewOrder}>Order again — try a twist</button>
      </div>
    );
  }
  if (report.decision === 'payment_declined') {
    return (
      <div className="final-card final-warn receipt2">
        <h3>Payment failed — nothing was charged</h3>
        <StateStamp state="BLOCKED" word="payment declined" />
        <p>
          Your {formatMoney(report.total_minor ?? 0)} is back in the cap. Order{' '}
          <span className="mono">{report.order_id}</span> is held — retrying is safe: the same
          order is reused, never a second one.
        </p>
        <p className="muted small">{report.constraints_unsatisfied[0]}</p>
        <button className="btn-ghost" onClick={onNewOrder}>New order</button>
      </div>
    );
  }
  return (
    <div className="final-card final-warn receipt2">
      <h3>Nothing was bought</h3>
      <StateStamp state="BLOCKED" word="declined honestly" />
      <p>{report.constraints_unsatisfied[0] ?? 'The request could not be satisfied as stated.'}</p>
      <p className="muted small">
        An agent that stretches your budget is spending money you did not agree to — declining is
        the correct behaviour. Cap untouched:{' '}
        <span className="mono">{formatMoney(snapshot.mandate?.remaining_minor ?? 0)}</span>.
      </p>
      <button className="btn-ghost" onClick={onNewOrder}>New order</button>
    </div>
  );
}
