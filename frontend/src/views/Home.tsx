// The landing page — a product's front door, not a project readme. The hero
// SHOWS the product working (a looping mock of the real flow, same copy the
// live demo produces); everything below answers, in order: how do I use it,
// why can I trust it, what's real, where's the machinery.

import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

// ---------------------------------------------------------------- live mock
// A miniature of the real order flow that plays itself on a loop. Pure UI —
// the amounts and copy mirror the actual demo run so nothing here overclaims.
const MOCK_STEPS = 8;

function LiveMock() {
  const [step, setStep] = useState(0);
  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setStep(MOCK_STEPS - 1);
      return;
    }
    const t = setInterval(() => setStep((s) => (s + 1) % MOCK_STEPS), 1400);
    return () => clearInterval(t);
  }, []);
  const on = (n: number) => step >= n;
  return (
    <div className="mock" aria-label="A preview of the live demo: a request becomes a priced cart and a real test-mode order">
      <div className="mock-head">
        <span className="mock-dot" /> <span className="mock-dot" /> <span className="mock-dot" />
        <span className="mock-title">conduit — live order</span>
      </div>
      <div className="mock-body">
        <div className={`mock-bubble mock-user ${on(0) ? 'mk-on' : ''}`}>
          Order dinner for four under ₹800, no beef
        </div>
        <div className={`mock-bubble mock-agent ${on(1) ? 'mk-on' : ''}`}>
          <span className="mock-avatar" aria-hidden="true" />
          On it — reading the menu. Prices come from the server, never from me.
        </div>
        <div className={`mock-bill ${on(2) ? 'mk-on' : ''}`}>
          <div className={`mock-line ${on(2) ? 'mk-on' : ''}`}>
            <span><span className="veg-mark" /> Steamed Rice ×4</span><span className="mono">₹360.00</span>
          </div>
          <div className={`mock-line ${on(3) ? 'mk-on' : ''}`}>
            <span><span className="veg-mark" /> Tandoori Roti ×4</span><span className="mono">₹100.00</span>
          </div>
          <div className={`mock-line ${on(4) ? 'mk-on' : ''}`}>
            <span><span className="veg-mark" /> Gulab Jamun (2 pc)</span><span className="mono">₹80.00</span>
          </div>
          <div className={`mock-line mock-total ${on(5) ? 'mk-on' : ''}`}>
            <span>To pay · re-priced at commit ✓</span><span className="mono">₹572.60</span>
          </div>
        </div>
        <div className={`mock-receipt ${on(6) ? 'mk-on' : ''}`}>
          <span className="mock-check" aria-hidden="true">✓</span>
          <span>
            Order placed — <span className="mono">order_TVWCd7DHE9KzQh</span>
            <span className="claim-chip claim-real">◆ Razorpay · test</span>
          </span>
        </div>
        <div className={`mock-note ${on(7) ? 'mk-on' : ''}`}>
          ₹1,427.40 still protected in your spending cap
        </div>
      </div>
    </div>
  );
}

const STEPS = [
  {
    n: '1',
    title: 'Set a spending cap — once',
    words:
      '“₹2,000 for this shop, this week.” That’s the only thing you ever approve. ' +
      'Revoke it any moment and it dies instantly.',
  },
  {
    n: '2',
    title: 'Say what you want',
    words:
      'Plain language: “dinner for four under ₹800, no beef.” The agent reads the menu, ' +
      'builds the cart, checks totals — all of it free, none of it touching money.',
  },
  {
    n: '3',
    title: 'Get a receipt you can trust',
    words:
      'One binding moment: the server re-prices everything against the live menu, checks ' +
      'your cap, and only then creates a real Razorpay test-mode order. Exactly one.',
  },
];

const RULES = [
  {
    title: 'The agent never does maths on money',
    words:
      'Every amount comes from a server response. In our eval a deliberately-flawed model got its own total wrong on 40.9% of attempts — and the charged amount was wrong zero times.',
  },
  {
    title: 'A price change cancels the deal, not your wallet',
    words:
      'If a price moves between browsing and buying, the commit is refused with a line-by-line diff. A stale price can never bind.',
  },
  {
    title: 'Your cap cannot be overridden — by anyone',
    words:
      'Running out of cap is a hard no. Not even a human reviewer can approve past it. And a dinner cap can never authorise a refund.',
  },
  {
    title: 'Never two charges',
    words:
      'Retry, timeout, or two agents racing — one order, one charge, proven with genuinely concurrent tests. On an unclear timeout it reconciles first, never blindly retries.',
  },
  {
    title: 'The shop’s words can’t boss the agent around',
    words:
      'Product descriptions are treated as untrusted data — here the attacker is the shop itself. Planted instructions are quarantined, and what slips past dies at your budget or your cap.',
  },
];

export function Home() {
  return (
    <div className="landing">
      <section className="hero2">
        <div className="hero2-copy">
          <p className="eyebrow">Razorpay Buildathon · Track 01 · Agentic commerce</p>
          <h1>
            Tell it what you want.<br />
            It orders. <em>It can’t overspend.</em>
          </h1>
          <p className="hero2-sub">
            CONDUIT is an AI buyer for real merchants. You set a spending cap once; the agent
            shops, a gate re-prices everything at the moment of truth, and a real Razorpay
            test-mode order comes out — with a receipt you can interrogate.
          </p>
          <div className="hero2-cta">
            <Link className="btn-cta" to="/buy">Watch it order dinner →</Link>
            <a className="btn-ghost" href="#how">How it works</a>
          </div>
          <div className="trust-strip" role="group" aria-label="Headline measurements">
            <span><strong className="mono">9/0</strong> agent arithmetic failures / wrong charges</span>
            <span><strong className="mono">100%</strong> amount accuracy</span>
            <span><strong className="mono">0</strong> double charges</span>
            <span><strong className="mono">0%</strong> legit purchases blocked</span>
          </div>
        </div>
        <div className="hero2-mock">
          <LiveMock />
        </div>
      </section>

      <section className="land-section" id="how">
        <h2>Three steps. One human approval.</h2>
        <div className="steps2">
          {STEPS.map((s) => (
            <div className="step2" key={s.n}>
              <span className="step2-n mono">{s.n}</span>
              <h3>{s.title}</h3>
              <p>{s.words}</p>
            </div>
          ))}
        </div>
        <p className="land-note">
          The trick that makes it safe <em>and</em> fast: the cart lives <strong>off the payment
          rail</strong>. Thinking is free and unlimited; committing is one audited, guarded moment.
        </p>
      </section>

      <section className="land-section">
        <h2>Five things it cannot do — even manipulated</h2>
        <p className="land-sub">
          Not promises in a prompt. Properties of the system, each with tests behind it.
        </p>
        <div className="rules2">
          {RULES.map((r) => (
            <div className="rule2" key={r.title}>
              <h3>{r.title}</h3>
              <p>{r.words}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="land-section honesty2">
        <h2>What’s real, what’s modelled — never blurred</h2>
        <p>
          <span className="claim-chip claim-real">◆ Razorpay · test</span> Every order id in this
          demo is minted by Razorpay’s API in test mode — a mock can’t produce one.{' '}
          <span className="claim-chip claim-modelled">▢ modelled</span> The menu, cart, spending
          cap, and payment rail are faithful models over those real primitives. You’ll see these
          chips on every panel — the line between built and real is part of the interface, on purpose.
        </p>
      </section>

      <section className="land-section">
        <h2>Try to break it</h2>
        <p className="land-sub">One-click failure stories — the parts most checkout demos hide:</p>
        <div className="twists">
          <Link to="/buy" className="twist-card">
            <span className="twist-glyph" aria-hidden="true">💳</span>
            <h3>Payment declines</h3>
            <p>Money returns to your cap, visibly. Retrying reuses the same order — never a second one.</p>
          </Link>
          <Link to="/buy" className="twist-card">
            <span className="twist-glyph" aria-hidden="true">🏷️</span>
            <h3>Price changes mid-purchase</h3>
            <p>The commit is refused with a line-by-line diff — the frame we’re proudest of: policy allowed the call, commerce refused the outcome.</p>
          </Link>
          <Link to="/buy" className="twist-card">
            <span className="twist-glyph" aria-hidden="true">⏱️</span>
            <h3>The rail times out</h3>
            <p>Did it go through? The agent doesn’t guess — it reconciles against the order’s real payment history first.</p>
          </Link>
        </div>
      </section>

      <section className="land-section byo">
        <div className="byo-copy">
          <h2>Bring a real store — any store</h2>
          <p>
            This isn’t a fixture-only trick. On the <strong>For merchants</strong> page, paste any
            product page that carries standard markup (schema.org JSON-LD — what mainstream store
            platforms emit) and its items become agent-sellable in seconds. We verified it against
            a real Indian storefront, live:
          </p>
          <ol className="byo-steps">
            <li>Pasted <span className="mono">bluetokaicoffee.com/products/attikan-estate</span> — a real coffee company’s live product page</li>
            <li>1 item imported from its JSON-LD: <strong>Attikan Estate · ₹700.00</strong>, description correctly held as untrusted data</li>
            <li>Asked the agent: <em>“Buy one Attikan Estate coffee under ₹900”</em> — it bought exactly that item, nothing else</li>
            <li>The merchant’s revenue view showed ₹700 captured via the agent channel</li>
          </ol>
          <p className="muted small">
            Structure only, never prose · INR only in this demo · imports never overwrite existing
            prices · the import fetch is live even on this hosted demo.
          </p>
        </div>
        <div className="hood-links">
          <Link to="/merchant" className="btn-cta">Try it with your store →</Link>
          <Link to="/buy" className="btn-ghost">Then order from it</Link>
        </div>
      </section>

      <section className="land-section hood">
        <div>
          <h2>Under the hood: SENTINEL</h2>
          <p>
            Every tool call the agent makes crosses a policy boundary before it executes:
            classified, quarantined, judged, and written to a tamper-evident audit ledger.
            The agent could be confidently wrong or actively manipulated — the boundary holds
            either way. That control plane is a full product of its own, and you can open it.
          </p>
        </div>
        <div className="hood-links">
          <Link to="/runs" className="btn-ghost">Run console</Link>
          <Link to="/audit" className="btn-ghost">Audit ledger</Link>
          <Link to="/redteam" className="btn-ghost">Red team results</Link>
        </div>
      </section>

      <footer className="land-footer">
        <p>
          <strong>Test mode only.</strong> Synthetic data, no real money, no credentials anywhere.
          Independent project integrating the open-source razorpay/razorpay-mcp-server — not
          affiliated with or endorsed by Razorpay or NPCI. Built on{' '}
          <a href="https://github.com/codeit-ronit/SENTINEL">SENTINEL</a>. Fixture mode:
          offline · deterministic · no credentials.
        </p>
      </footer>
    </div>
  );
}
