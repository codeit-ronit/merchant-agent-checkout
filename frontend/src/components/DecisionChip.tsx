import type { DecisionState } from '../types';

// Decision state is the primary information carried by colour — and it must be
// legible WITHOUT colour. Every state pairs a semantic colour with a fixed
// glyph, so a colour-blind operator reads the glyph and the word, never the hue.
const GLYPH: Record<DecisionState, string> = {
  ALLOW: '✓',
  DENY: '✕',
  REQUIRE_APPROVAL: '▲',
  AWAITING: '⏱',
};

// Operator-side vocabulary. The word an operator would say, not the enum.
const LABEL: Record<DecisionState, string> = {
  ALLOW: 'Allowed',
  DENY: 'Blocked',
  REQUIRE_APPROVAL: 'Needs approval',
  AWAITING: 'Awaiting review',
};

const CLASS: Record<DecisionState, string> = {
  ALLOW: 'chip-allow',
  DENY: 'chip-deny',
  REQUIRE_APPROVAL: 'chip-escalate',
  AWAITING: 'chip-awaiting',
};

export function toDecisionState(
  disposition: string | null | undefined,
  fallback: DecisionState = 'AWAITING'
): DecisionState {
  switch (disposition) {
    case 'ALLOW':
    case 'DENY':
    case 'REQUIRE_APPROVAL':
      return disposition;
    case 'AWAITING':
      return 'AWAITING';
    default:
      return fallback;
  }
}

export function DecisionChip({
  state,
  label,
  size = 'md',
}: {
  state: DecisionState;
  label?: string;
  size?: 'sm' | 'md' | 'lg';
}) {
  return (
    <span className={`decision-chip ${CLASS[state]} chip-${size}`}>
      <span className="chip-glyph" aria-hidden="true">
        {GLYPH[state]}
      </span>
      <span className="chip-label">{label ?? LABEL[state]}</span>
    </span>
  );
}
