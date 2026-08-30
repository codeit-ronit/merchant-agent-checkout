import { NavLink } from 'react-router-dom';

interface NavItem {
  to: string;
  label: string;
  glyph: string;
  job: string;
}

// Six views, one job each. The glyphs are simple line marks (not brand icons).
const ITEMS: NavItem[] = [
  { to: '/', label: '← The demo site', glyph: '⌂', job: 'Back to the product' },
  { to: '/runs', label: 'Run console', glyph: '▤', job: 'Watch a run decide' },
  { to: '/approvals', label: 'Approvals', glyph: '⏱', job: 'Authorize or reject' },
  { to: '/policies', label: 'Policies', glyph: '§', job: 'Read & dry-run' },
  { to: '/evals', label: 'Evaluations', glyph: '▦', job: 'Model vs enforcement' },
  { to: '/redteam', label: 'Red team', glyph: '⚔', job: 'Attacks off vs on' },
  { to: '/audit', label: 'Audit ledger', glyph: '⛓', job: 'Verify the chain' },
];

export function NavRail() {
  return (
    <nav className="nav-rail" aria-label="Primary">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <div className="nav-brand">
        <span className="nav-seal" aria-hidden="true">
          ⬡
        </span>
        <span className="nav-wordmark">
          SENTINEL
          <small>the control plane under CONDUIT</small>
        </span>
      </div>
      <ul className="nav-list">
        {ITEMS.map((it) => (
          <li key={it.to}>
            <NavLink
              to={it.to}
              end={it.to === '/'}
              className={({ isActive }) => (isActive ? 'nav-link nav-link--active' : 'nav-link')}
            >
              <span className="nav-glyph" aria-hidden="true">
                {it.glyph}
              </span>
              <span className="nav-text">
                <span className="nav-label">{it.label}</span>
                <span className="nav-job">{it.job}</span>
              </span>
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="nav-foot">
        <span className="nav-foot-mode">FIXTURE MODE</span>
        <span className="nav-foot-note">Offline · deterministic · no credentials</span>
      </div>
    </nav>
  );
}
