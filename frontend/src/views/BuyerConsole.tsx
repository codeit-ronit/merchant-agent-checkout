// The split view — the signature (frontend/DESIGN.md §3). Conversation on
// the left, machinery on the right, both driven by the SAME paced event
// stream, so the synchrony is structural: the agent says "adding rice" as
// the line appears, the total recomputes, and the mandate bar shrinks.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { createMandate, listMandates, startPurchase } from '../api';
import { formatMoney } from '../format';
import type { BuyerReport, CommerceSnapshot, MandateView } from '../types';
import {
  CartPanel,
  ClaimChip,
  EventRow,
  MandateMeter,
  StateStamp,
  narrate,
  useCommerceStream,
} from '../components/commerce';

const DEFAULT_TASK = 'Order dinner for four under ₹800, no beef';

export function BuyerConsole() {
  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [mandateId, setMandateId] = useState<string>('');
  const [amount, setAmount] = useState('2000');
  const [task, setTask] = useState(DEFAULT_TASK);
  const [demo, setDemo] = useState<'none' | 'decline' | 'timeout' | 'reprice'>('none');
  const [runRef, setRunRef] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  // the latest snapshot drives the machinery; done-result wins at the end
  const snapshot: CommerceSnapshot | null = useMemo(() => {
    if (status === 'done' && result) return result.final_snapshot;
    return events.length ? events[events.length - 1].commerce : null;
  }, [events, result, status]);

  const liveMandate =
    snapshot?.mandate ?? mandates.find((m) => m.mandate_id === mandateId) ?? null;

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

  return (
    <div className="buyer-shell">
      <section className="buyer-left" aria-label="Conversation">
        <div className="commerce-panel">
          <div className="panel-head">
            <h3>Set money aside</h3>
            <span className="muted small">the one human step</span>
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
            <span className="muted small">for Fresh Basket · 7 days · revocable</span>
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
            <h3>Ask the agent</h3>
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
          <div className="panel-head"><h3>The agent</h3></div>
          {narration.length === 0 && status !== 'streaming' && (
            <p className="muted">Nothing yet — send a request. The agent narrates here while the machinery moves on the right.</p>
          )}
          <ul className="convo-lines">
            {narration.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
          {result?.output && <FinalCard report={result.output} snapshot={result.final_snapshot} />}
        </div>
      </section>

      <section className="buyer-right" aria-label="The machinery">
        <div className="panel-head machinery-head">
          <h3>The machinery</h3>
          <ClaimChip kind="modelled" />
          <ClaimChip kind="real" />
          <span className="muted small">catalog, cart, mandate & rail are modelled; every order id is Razorpay-minted</span>
        </div>
        <MandateMeter mandate={liveMandate} />
        <CartPanel cart={snapshot?.cart ?? null} />
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
          {report.upsell_accepted ? 'includes a merchant offer you can see marked in the cart' : 'no extras added'}
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
