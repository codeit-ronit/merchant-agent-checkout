// The product's navbar — the demo-facing shell. The operator control room
// (SENTINEL's rail) is one link away under "Under the hood", where machinery
// belongs: present, honest, not the headline.

import { NavLink, Link } from 'react-router-dom';
import { useTheme } from '../useTheme';

const THEME_GLYPH: Record<string, string> = { system: '◐', light: '☀', dark: '☾' };

export function TopNav() {
  const { choice, cycle } = useTheme();
  return (
    <header className="topnav">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <Link to="/" className="brand" aria-label="CONDUIT home">
        <span className="brand-mark" aria-hidden="true">●</span>
        <span className="brand-word">conduit</span>
        <span className="brand-tag">AI buyer · test mode</span>
      </Link>
      <nav className="topnav-links" aria-label="Primary">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'tn-link tn-active' : 'tn-link')}>
          How it works
        </NavLink>
        <NavLink to="/buy" className={({ isActive }) => (isActive ? 'tn-link tn-active' : 'tn-link')}>
          Order with the agent
        </NavLink>
        <NavLink to="/merchant" className={({ isActive }) => (isActive ? 'tn-link tn-active' : 'tn-link')}>
          For merchants
        </NavLink>
        <Link to="/runs" className="tn-link tn-hood" title="SENTINEL — the control plane every tool call passes through">
          Under the hood ↗
        </Link>
      </nav>
      <button type="button" className="tn-theme" onClick={cycle}
        aria-label={`Theme: ${choice}. Activate to change.`} title={`Theme: ${choice}`}>
        {THEME_GLYPH[choice]}
      </button>
    </header>
  );
}
