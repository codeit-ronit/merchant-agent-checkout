import { useTheme } from '../useTheme';

const THEME_GLYPH: Record<string, string> = {
  system: '◐',
  light: '☀',
  dark: '☾',
};

const THEME_LABEL: Record<string, string> = {
  system: 'System theme',
  light: 'Light theme',
  dark: 'Dark theme',
};

export function Header() {
  const { choice, cycle } = useTheme();
  return (
    <header className="app-header">
      <div className="header-notice" role="note">
        <span className="notice-dot" aria-hidden="true" />
        <span>
          <strong>Test mode only</strong>
          <span className="notice-sep"> · </span>
          independent Buildathon submission
        </span>
      </div>
      <div className="header-actions">
        <button
          type="button"
          className="theme-toggle"
          onClick={cycle}
          aria-label={`Theme: ${THEME_LABEL[choice]}. Activate to change.`}
          title={`${THEME_LABEL[choice]} — click to change`}
        >
          <span className="theme-glyph" aria-hidden="true">
            {THEME_GLYPH[choice]}
          </span>
          <span className="theme-text">{THEME_LABEL[choice]}</span>
        </button>
      </div>
    </header>
  );
}
