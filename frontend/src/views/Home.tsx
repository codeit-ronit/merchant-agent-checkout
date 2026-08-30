// The front door — the project explained in plain words, for someone who has
// never seen it. The hero is the earned measurement; everything below answers
// "what is going on here?" before the visitor clicks into the live demo.

import { Link } from 'react-router-dom';

const STEPS = [
  {
    glyph: '●',
    title: 'You set money aside — once',
    words:
      '“₹2,000 for this shop, this week.” That single approval is the only ' +
      'human step. You can revoke it at any moment, and it dies instantly.',
  },
  {
    glyph: '▤',
    title: 'The agent shops, for free',
    words:
      'It reads the catalog, builds a cart, swaps things, checks totals — and ' +
      'none of that touches your money. The server does every bit of the ' +
      'maths; the agent never computes a price.',
  },
  {
    glyph: '⌖',
    title: 'One binding moment',
    words:
      'At commit, the server re-prices the whole cart against live truth and ' +
      'checks your limit. Only if everything holds is a real Razorpay order ' +
      'created — exactly one.',
  },
  {
    glyph: '⛓',
    title: 'A receipt you can interrogate',
    words:
      'What was bought, what it cost, which rule allowed it, which merchant ' +
      'offer was accepted — every step lands in a tamper-evident audit log.',
  },
];

const RULES = [
  {
    title: 'The agent never does maths on money',
    words:
      'Every amount it acts on came back from a server response. In our eval, a ' +
      'deliberately-flawed model got its own total wrong on 40.9% of attempts — ' +
      'and the charged amount was wrong zero times, because the gate catches ' +
      'every mis-statement.',
  },
  {
    title: 'A price change cancels the deal, not your wallet',
    words:
      'If a price moves between browsing and buying, the commit is rejected with ' +
      'a line-by-line diff — old price, new price, why — and the agent must ' +
      're-confirm at the true amount. A stale price can never bind.',
  },
  {
    title: 'Your limit cannot be overridden — by anyone',
    words:
      'Running out of mandate is a hard no. Not even a human reviewer can ' +
      'approve past a limit you set. And a dinner mandate can never authorise ' +
      'a refund — consent to a purchase is not consent to move money.',
  },
  {
    title: 'Never two charges',
    words:
      'Retry, timeout, or two agents racing — one order, one charge, proven ' +
      'with genuinely concurrent tests. On an unclear timeout the system ' +
      'reconciles first; it never blindly retries a payment.',
  },
  {
    title: 'The merchant’s words can’t boss the agent around',
    words:
      'Product descriptions are treated as untrusted data — in this threat ' +
      'model the attacker is the shop itself. Instructions planted in a ' +
      'description are quarantined, and what slips past dies at your budget ' +
      'or your mandate.',
  },
];

export function Home() {
  return (
    <div className="home">
      <section className="hero">
        <p className="hero-eyebrow">Razorpay Buildathon · Track 01 · Agentic Commerce</p>
        <h1 className="hero-title">
          An AI agent that can <em>actually buy things</em> — and can’t overspend.
        </h1>
        <p className="hero-sub">
          CONDUIT makes any Razorpay merchant sellable to an AI buyer: say{' '}
          <strong>“order dinner for four under ₹800, no beef”</strong> and watch it become a real
          test-mode Razorpay order — inside a spending limit you approved once, upfront.
        </p>
        <div className="hero-cta">
          <Link className="btn btn-primary btn-big" to="/buy">
            ▶ Watch a purchase happen
          </Link>
          <Link className="btn btn-big" to="/merchant">
            The merchant’s side
          </Link>
        </div>
        <div className="hero-stats" role="group" aria-label="Headline measurements">
          <div className="stat">
            <span className="stat-num mono">9 / 0</span>
            <span className="stat-words">arithmetic failures / wrong charges — the whole idea, measured</span>
          </div>
          <div className="stat">
            <span className="stat-num mono">100%</span>
            <span className="stat-words">amount accuracy — a single wrong charge fails our test suite</span>
          </div>
          <div className="stat">
            <span className="stat-num mono">0%</span>
            <span className="stat-words">legitimate purchases blocked — safety that doesn’t tax commerce</span>
          </div>
          <div className="stat">
            <span className="stat-num mono">0</span>
            <span className="stat-words">double charges · mandate violations — under retry, timeout, and races</span>
          </div>
        </div>
      </section>

      <section className="home-section">
        <h2>How it works — the whole loop in four steps</h2>
        <div className="step-grid">
          {STEPS.map((s, i) => (
            <div className="step-card" key={s.title}>
              <div className="step-head">
                <span className="step-glyph" aria-hidden="true">{s.glyph}</span>
                <span className="step-index mono">{i + 1}</span>
              </div>
              <h3>{s.title}</h3>
              <p>{s.words}</p>
            </div>
          ))}
        </div>
        <p className="muted center">
          The trick that makes it safe <em>and</em> fast: the cart lives <strong>off the payment
          rail</strong>. Thinking is free and unlimited; committing is one audited, guarded moment.
        </p>
      </section>

      <section className="home-section">
        <h2>The rules the agent cannot break</h2>
        <p className="muted">
          Not promises in a prompt — properties of the system, each with tests behind it. The agent
          could be confidently wrong or actively manipulated, and these still hold.
        </p>
        <div className="rule-list">
          {RULES.map((r) => (
            <div className="rule-card" key={r.title}>
              <h3>✓ {r.title}</h3>
              <p>{r.words}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-section honesty">
        <h2>What’s real, what’s modelled — never blurred</h2>
        <p>
          <span className="claim-chip claim-real">◆ Razorpay · test</span> Every order id in this
          demo is minted by Razorpay’s API surface in test mode — a mock can’t produce one.{' '}
          <span className="claim-chip claim-modelled">▢ modelled</span> The catalog, cart, spending
          mandate, and the payment rail are faithful models over those real primitives (the
          server-to-server payment API is gated on our test account). You’ll see these chips on
          every panel — the line between built and real is part of the interface, on purpose.
        </p>
      </section>

      <section className="home-section">
        <h2>Try breaking it</h2>
        <p className="muted">
          The demo has one-click failure stories — the parts most checkout demos hide:
        </p>
        <div className="try-grid">
          <Link to="/buy" className="try-card">
            <h3>Payment declines</h3>
            <p>The order is held, your money returns visibly to the mandate, and retrying is safe — the same order is reused, never a second one.</p>
          </Link>
          <Link to="/buy" className="try-card">
            <h3>Price changes mid-purchase</h3>
            <p>The commit is refused with a line-by-line diff, and you’ll see the frame this project is proudest of: <em>policy allowed the call, commerce refused the outcome</em> — both true, side by side.</p>
          </Link>
          <Link to="/buy" className="try-card">
            <h3>The rail times out</h3>
            <p>Did the payment go through? The agent doesn’t guess and doesn’t blindly retry — it reconciles against the order’s real payment history first.</p>
          </Link>
        </div>
      </section>

      <footer className="home-footer">
        <p>
          <strong>Test mode only.</strong> Synthetic data, no real money, no credentials anywhere.
          Independent project integrating the open-source razorpay/razorpay-mcp-server — not
          affiliated with or endorsed by Razorpay or NPCI. Built on{' '}
          <a href="https://github.com/codeit-ronit/SENTINEL">SENTINEL</a>, our policy-enforcement
          control plane: every tool call the agent makes is classified, quarantined, and judged
          before it executes.
        </p>
      </footer>
    </div>
  );
}
