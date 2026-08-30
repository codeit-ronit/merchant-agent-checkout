// The order experience — a food-app you watch an AI use (frontend/DESIGN.md §3,
// reworked). Three columns over one paced event stream: the restaurant menu the
// agent shops from (items light up as they land in the cart), the conversation,
// and the bill. Above them, the journey tracker makes the pipeline itself
// visible: consent → shopping → commit gate → Razorpay order → payment, each
// stage flipping on the event that actually happened — never on a timer.

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
  AgentOrb,
  BillPanel,
  ClaimChip,
  EventRow,
  JourneyTracker,
  MandateMeter,
  StateStamp,
  Typing,
  VegMark,
  narrate,
  useCommerceStream,
} from '../components/commerce';
import type { JourneyStage } from '../components/commerce';

const DEFAULT_TASK = 'Order dinner for four under ₹800, no beef';

// Emoji tiles for the menu — keyword-mapped, CSP-safe (no external images).
const DISH_GLYPHS: Array<[RegExp, string]> = [
  [/beef/i, '🥩'], [/chicken/i, '🍗'], [/dal/i, '🍲'], [/thali/i, '🍱'],
  [/naan|roti/i, '🫓'], [/jamun/i, '🍮'], [/chaas|lassi/i, '🥛'],
  [/paneer/i, '🧆'], [/rice/i, '🍚'], [/biryani/i, '🍛'],
];
function dishGlyph(name: string): string {
  for (const [re, g] of DISH_GLYPHS) if (re.test(name)) return g;
  return '🍽️';
}
function isVeg(item: CatalogItemView): boolean {
  return item.attributes.includes('veg');
}

// ---------------------------------------------------------------- journey
// Stage derivation — pure function of the stream, so the tracker can never
// disagree with the machinery panels beside it.
function deriveJourney(
  events: CommerceTraceEvent[],
  result: PurchaseResult | null,
  streaming: boolean,
  mandate: MandateView | null,
  cart: CartView | null,
): JourneyStage[] {
  const running = streaming;
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

  // 1 — consent
  const consent: JourneyStage = mandate
    ? { key: 'consent', label: 'Consent', state: 'done', sub: `${formatMoney(mandate.locked_minor)} set aside` }
    : { key: 'consent', label: 'Consent', state: 'pending', sub: 'set money aside' };

  // 2 — the agent shops (off the payment rail: free, unlimited)
  let shop: JourneyStage = { key: 'shop', label: 'Agent shops', state: 'pending', sub: 'off-rail · free' };
  if (running && !commitForwarded) {
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

  // 3 — the commit gate (re-price against live truth, check the limit)
  let gate: JourneyStage = { key: 'gate', label: 'Commit gate', state: 'pending', sub: 're-price · limit' };
  if (commitForwarded && !latestCommit) {
    gate = { key: 'gate', label: 'Commit gate', state: 'active', sub: 're-pricing…' };
  } else if (committedOk) {
    gate = { key: 'gate', label: 'Commit gate', state: 'done',
      sub: refusedOnce ? 'refused once → re-confirmed' : `re-priced ✓ ${cart ? formatMoney(cart.total_minor) : ''}` };
  } else if (refusedOnce) {
    gate = { key: 'gate', label: 'Commit gate', state: finished ? 'fail' : 'active',
      sub: 'price changed — refused' };
  }

  // 4 — the real Razorpay order
  const order: JourneyStage = orderId
    ? { key: 'order', label: 'Razorpay order', state: 'done', sub: orderId, real: true }
    : { key: 'order', label: 'Razorpay order', state: committedOk ? 'active' : 'pending', sub: 'real · test mode' };

  // 5 — payment on the modelled rail
  let pay: JourneyStage = { key: 'pay', label: 'Payment', state: 'pending', sub: 'modelled rail' };
  if (payment) {
    if (payment.status === 'captured') {
      pay = { key: 'pay', label: 'Payment', state: 'done', sub: 'captured ✓' };
    } else if (payment.status === 'failed' || decision === 'payment_declined') {
      pay = { key: 'pay', label: 'Payment', state: 'fail', sub: 'declined — money returned' };
    } else {
      pay = { key: 'pay', label: 'Payment', state: 'active', sub: payment.status };
    }
  } else if (decision === 'payment_declined') {
    pay = { key: 'pay', label: 'Payment', state: 'fail', sub: 'declined — money returned' };
  } else if (reconciling) {
    pay = { key: 'pay', label: 'Payment', state: 'active', sub: 'reconciling…' };
  } else if (orderId && running) {
    pay = { key: 'pay', label: 'Payment', state: 'active', sub: 'paying…' };
  }

  return [consent, shop, gate, order, pay];
}

// ---------------------------------------------------------------- the menu
function MenuPanel({ items, merchantName, version, cart }: {
  items: CatalogItemView[];
  merchantName: string;
  version: number;
  cart: CartView | null;
}) {
  const inCart = new Map((cart?.lines ?? []).map((l) => [l.item_id, l]));
  const ordered = [...items].sort((a, b) =>
    Number(a.stock === 'OUT_OF_STOCK') - Number(b.stock === 'OUT_OF_STOCK'));
  return (
    <div className="commerce-panel menu-panel">
      <div className="resto-head">
        <span className="resto-tile" aria-hidden="true">🧺</span>
        <div>
          <h3>{merchantName || 'Fresh Basket'}</h3>
          <p className="muted small">Indian · veg &amp; non-veg · catalog v{version} <ClaimChip kind="modelled" /></p>
        </div>
      </div>
      <p className="muted small menu-note">
        The menu the agent reads. Watch items light up as it adds them — it can pick anything,
        but it can never write a price.
      </p>
      <ul className="dish-list">
        {ordered.map((it) => {
          const line = inCart.get(it.item_id);
          const soldOut = it.stock === 'OUT_OF_STOCK';
          return (
            <li key={it.item_id}
              className={`dish-card${line ? ' dish-in-cart' : ''}${soldOut ? ' dish-out' : ''}`}>
              <span className="dish-tile" aria-hidden="true">{dishGlyph(it.name)}</span>
              <div className="dish-body">
                <div className="dish-top">
                  <VegMark veg={isVeg(it)} />
                  <span className="dish-name">{it.name}</span>
                </div>
                <span className="mono dish-price">{formatMoney(it.price_minor)}</span>
                {it.description && <p className="dish-desc muted small">{it.description}</p>}
                {soldOut && <span className="dish-badge dish-badge-out">sold out</span>}
                {!soldOut && it.stock === 'LIMITED' && it.stock_count != null && (
                  <span className="dish-badge">only {it.stock_count} left</span>
                )}
                {line && (
                  <span className="dish-badge dish-badge-agent">
                    in cart ×{line.quantity} — added by the agent
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function BuyerConsole() {
  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [mandateId, setMandateId] = useState<string>('');
  const [amount, setAmount] = useState('2000');
  const [task, setTask] = useState(DEFAULT_TASK);
  const [demo, setDemo] = useState<'none' | 'decline' | 'timeout' | 'reprice'>('none');
  const [runRef, setRunRef] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState<CatalogItemView[]>([]);
  const [merchantName, setMerchantName] = useState('');
  const [catalogVersion, setCatalogVersion] = useState(0);
  const { events, result, status } = useCommerceStream(runRef);

  const refreshMandates = useCallback(async () => {
    try {
      const list = await listMandates();
      setMandates(list);
      if (!mandateId && list.length) setMandateId(list[list.length - 1].mandate_id);
    } catch {
      /* surfaced by the empty state */
    }
  }, [mandateId]);

  useEffect(() => {
    void refreshMandates();
  }, [refreshMandates]);

  useEffect(() => {
    getCommerceCatalog()
      .then((cat) => {
        setMenu(cat.items);
        setMerchantName(cat.merchant.display_name);
        setCatalogVersion(cat.catalog_version);
      })
      .catch(() => { /* menu column shows nothing; the run still works */ });
  }, []);

  // the latest snapshot drives the machinery; done-result wins at the end
  const snapshot: CommerceSnapshot | null = useMemo(() => {
    if (status === 'done' && result) return result.final_snapshot;
    return events.length ? events[events.length - 1].commerce : null;
  }, [events, result, status]);

  const liveMandate =
    snapshot?.mandate ?? mandates.find((m) => m.mandate_id === mandateId) ?? null;
  const liveCart = snapshot?.cart ?? null;

  const journey = useMemo(
    () => deriveJourney(events, result, status === 'streaming', liveMandate, liveCart),
    [events, result, status, liveMandate, liveCart]);

  const vegByItem = useMemo(
    () => new Map(menu.map((it) => [it.item_id, isVeg(it)])), [menu]);

  const narration = useMemo(() => {
    const lines: string[] = [];
    events.forEach((evt, i) => {
      const prev = i > 0 ? events[i - 1].commerce : null;
      const words = narrate(evt, prev);
      if (words && lines[lines.length - 1] !== words) lines.push(words);
    });
    return lines;
  }, [events]);

  async function setAside() {
    setError(null);
    const rupees = Number(amount);
    if (!Number.isFinite(rupees) || rupees <= 0) {
      setError('Enter the amount to set aside, in rupees.');
      return;
    }
    try {
      const m = await createMandate(Math.round(rupees) * 100);
      setMandates((prior) => [...prior, m]);
      setMandateId(m.mandate_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not set the mandate aside.');
    }
  }

  async function send() {
    if (!mandateId) {
      setError('Set a mandate aside first — the agent can only spend consented money.');
      return;
    }
    setBusy(true);
    setError(null);
    setRunRef(null);
    try {
      const res = await startPurchase({
        task,
        mandate_id: mandateId,
        decline_demo: demo === 'decline',
        timeout_demo: demo === 'timeout',
        reprice_demo: demo === 'reprice',
      });
      setRunRef(res.run_ref);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The purchase could not start.');
    } finally {
      setBusy(false);
      void refreshMandates();
    }
  }

  async function runWholeDemo() {
    setBusy(true);
    setError(null);
    setRunRef(null);
    try {
      let mid = mandates.find((m) => m.status === 'ACTIVE' && m.remaining_minor >= 80000)?.mandate_id;
      if (!mid) {
        const m = await createMandate(200000);
        setMandates((prior) => [...prior, m]);
        mid = m.mandate_id;
      }
      setMandateId(mid);
      setDemo('none');
      const res = await startPurchase({ task: DEFAULT_TASK, mandate_id: mid });
      setRunRef(res.run_ref);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'The demo could not start.');
    } finally {
      setBusy(false);
      void refreshMandates();
    }
  }

  return (
    <div className="buyer-shell cx zshell">
      <div className="demo-banner">
        <div>
          <strong>The live demo.</strong>{' '}
          <span className="muted">
            An AI agent orders dinner from a real menu. One click does everything: sets ₹2,000
            aside and asks for dinner — then watch the journey bar and the bill move together.
          </span>
        </div>
        <button className="cx-btn cx-btn-primary" onClick={() => void runWholeDemo()}
          disabled={busy || status === 'streaming'}>
          {busy || status === 'streaming' ? 'Shopping…' : '▶ Run the whole demo'}
        </button>
      </div>

      <JourneyTracker stages={journey} />

      <div className="zgrid">
        <section className="menu-col" aria-label="The restaurant menu">
          <MenuPanel items={menu} merchantName={merchantName} version={catalogVersion} cart={liveCart} />
        </section>

        <section className="convo-col" aria-label="Conversation">
          <div className="commerce-panel">
            <div className="panel-head">
              <span className="step-tag mono">1</span>
              <h3>Set money aside</h3>
              <span className="muted small">the one human step — revocable anytime</span>
            </div>
            <div className="mandate-create">
              <span className="mono mandate-rupee">₹</span>
              <input
                className="mandate-input mono"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                inputMode="numeric"
                aria-label="Amount to set aside, rupees"
              />
              <span className="muted small">for {merchantName || 'Fresh Basket'} · 7 days · revocable</span>
              <button className="btn btn-primary" onClick={() => void setAside()}>
                Set aside
              </button>
            </div>
            {mandates.length > 0 && (
              <div className="mandate-list">
                {mandates.map((m) => (
                  <label key={m.mandate_id} className="mandate-option">
                    <input
                      type="radio"
                      name="mandate"
                      checked={mandateId === m.mandate_id}
                      onChange={() => setMandateId(m.mandate_id)}
                    />
                    <StateStamp state={m.status} />
                    <span className="mono">{formatMoney(m.remaining_minor)} </span>
                    <span className="muted small mono">{m.mandate_id}</span>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="commerce-panel">
            <div className="panel-head">
              <span className="step-tag mono">2</span>
              <h3>Ask the agent</h3>
              <span className="muted small">plain language in; a real order out</span>
            </div>
            <textarea
              className="task-input"
              value={task}
              onChange={(e) => setTask(e.target.value)}
              rows={2}
              aria-label="What should the agent buy?"
            />
            <div className="demo-row">
              <span className="muted small">Show a failure handled gracefully:</span>
              {(['none', 'decline', 'timeout', 'reprice'] as const).map((d) => (
                <label key={d} className="small">
                  <input type="radio" name="demo" checked={demo === d} onChange={() => setDemo(d)} />{' '}
                  {d === 'none' ? 'clean run' : d === 'decline' ? 'payment declines' : d === 'timeout' ? 'rail times out' : 'price changes mid-purchase'}
                </label>
              ))}
            </div>
            <button className="btn btn-primary" onClick={() => void send()} disabled={busy || status === 'streaming'}>
              {busy || status === 'streaming' ? 'Shopping…' : 'Send'}
            </button>
            {error && <p className="error-words" role="alert">{error}</p>}
          </div>

          <div className="commerce-panel convo" aria-live="polite">
            <div className="panel-head">
              <AgentOrb active={status === 'streaming'} size={26} />
              <h3>The agent</h3>
              {status === 'streaming' && <span className="muted small">working…</span>}
            </div>
            {narration.length === 0 && status !== 'streaming' && (
              <p className="muted">Nothing yet — send a request. The agent narrates here while the menu, bill, and journey bar move in the same beat.</p>
            )}
            <ul className="convo-lines">
              {narration.map((line, i) => (
                <li key={i}>{line}</li>
              ))}
              {status === 'streaming' && (
                <li className="typing-line" aria-hidden="true"><Typing /></li>
              )}
            </ul>
            {result?.output && <FinalCard report={result.output} snapshot={result.final_snapshot} />}
          </div>
        </section>

        <section className="bill-col" aria-label="The bill and the machinery">
          <div className="panel-head machinery-head">
            <h3>The machinery — live</h3>
            <ClaimChip kind="modelled" />
            <ClaimChip kind="real" />
          </div>
          <MandateMeter mandate={liveMandate} />
          <BillPanel cart={liveCart} vegOf={(id) => vegByItem.get(id)} />
          <div className="commerce-panel">
            <div className="panel-head"><h3>Decisions</h3></div>
            {events.length === 0 && <p className="muted">Every policy verdict and every commerce outcome lands here, stamped, with its reason.</p>}
            <div className="event-feed">
              {events.map((evt) => (
                <EventRow key={evt.sequence} evt={evt} />
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

// The receipt / the failure card — designed states, not residue (DESIGN.md §6).
function FinalCard({ report, snapshot }: { report: BuyerReport; snapshot: CommerceSnapshot }) {
  if (report.decision === 'purchased') {
    return (
      <div className="final-card final-ok">
        <div className="panel-head">
          <h3>Receipt</h3>
          <StateStamp state="COMMITTED" />
        </div>
        <p className="receipt-amount mono">{formatMoney(report.total_minor ?? 0)}</p>
        <p>
          Order <span className="mono">{report.order_id}</span> <ClaimChip kind="real" /> · payment{' '}
          <span className="mono">{report.payment_status}</span> <ClaimChip kind="modelled" />
        </p>
        <p className="muted small">
          {formatMoney(report.mandate_remaining_minor ?? 0)} left in your mandate ·{' '}
          {report.upsell_accepted ? 'includes a merchant offer you can see marked in the bill' : 'no extras added'}
        </p>
      </div>
    );
  }
  if (report.decision === 'payment_declined') {
    return (
      <div className="final-card final-warn">
        <div className="panel-head">
          <h3>Payment failed — nothing was charged</h3>
          <StateStamp state="BLOCKED" word="payment declined" />
        </div>
        <p>
          Your {formatMoney(report.total_minor ?? 0)} is back in the mandate. Order{' '}
          <span className="mono">{report.order_id}</span> is held — retrying is safe: the same
          order is reused, never a second one.
        </p>
        <p className="muted small">{report.constraints_unsatisfied[0]}</p>
      </div>
    );
  }
  return (
    <div className="final-card final-warn">
      <div className="panel-head">
        <h3>Nothing was bought</h3>
        <StateStamp state="BLOCKED" word="declined honestly" />
      </div>
      <p>{report.constraints_unsatisfied[0] ?? 'The request could not be satisfied as stated.'}</p>
      <p className="muted small">
        An agent that stretches your budget is spending money you did not agree to — declining is
        the correct behaviour. Mandate untouched:{' '}
        <span className="mono">{formatMoney(snapshot.mandate?.remaining_minor ?? 0)}</span>.
      </p>
    </div>
  );
}
