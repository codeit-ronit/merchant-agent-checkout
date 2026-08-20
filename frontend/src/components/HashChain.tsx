import type { Disposition } from '../types';
import { shortHash } from '../format';
import { toDecisionState } from './DecisionChip';

export interface ChainLink {
  sequence: number;
  entry_hash: string;
  previous_hash: string;
  tool_name: string;
  disposition: Disposition | null;
}

const DISP_GLYPH: Record<string, string> = {
  ALLOW: '✓',
  DENY: '✕',
  REQUIRE_APPROVAL: '▲',
  AWAITING: '⏱',
};

// The signature element. Each entry is a sealed block whose previous_hash must
// equal the prior block's entry_hash. When `breakAt` is set, the link leading
// INTO that sequence is snapped and every block from there on is shown as
// orphaned — the chain visibly breaks at the exact tampered position.
export function HashChain({
  links,
  breakAt,
}: {
  links: ChainLink[];
  breakAt: number | null;
}) {
  const broken = breakAt !== null;
  return (
    <div className="hashchain" role="img" aria-label={buildAria(links, breakAt)}>
      {links.map((link, i) => {
        const state = toDecisionState(link.disposition ?? undefined, 'AWAITING');
        const isBreakHere = broken && link.sequence === breakAt;
        const isAfterBreak = broken && breakAt !== null && link.sequence > breakAt;
        const orphaned = isBreakHere || isAfterBreak;
        return (
          <div className="hashchain-cell" key={link.sequence}>
            {i > 0 ? (
              <Connector broken={isBreakHere} dimmed={isAfterBreak} />
            ) : (
              <div className="hashchain-anchor" aria-hidden="true">
                genesis
              </div>
            )}
            <div
              className={
                'hashchain-block' +
                (orphaned ? ' hashchain-block--orphan' : '') +
                ` state-${state.toLowerCase()}`
              }
              title={`#${link.sequence} · ${link.tool_name}\nentry:  ${link.entry_hash}\nprev:   ${link.previous_hash}`}
            >
              <div className="hashchain-seq">
                <span className="hashchain-index mono">#{link.sequence}</span>
                <span className={`hashchain-disp disp-${state.toLowerCase()}`} aria-hidden="true">
                  {DISP_GLYPH[state]}
                </span>
              </div>
              <div className="hashchain-tool mono">{link.tool_name}</div>
              <div className="hashchain-hash mono">{shortHash(link.entry_hash, 8, 4)}</div>
              {orphaned ? <div className="hashchain-brokentag">unverifiable</div> : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Connector({ broken, dimmed }: { broken: boolean; dimmed: boolean }) {
  const cls = 'hashchain-connector' + (broken ? ' is-broken' : dimmed ? ' is-dimmed' : '');
  return (
    <div className={cls} aria-hidden="true">
      <svg viewBox="0 0 48 24" width="48" height="24" preserveAspectRatio="none">
        {broken ? (
          <>
            <path className="link-a" d="M2 12 h16" fill="none" strokeWidth="2.5" strokeLinecap="round" />
            <path className="link-b" d="M30 12 h16" fill="none" strokeWidth="2.5" strokeLinecap="round" />
            <path className="link-break" d="M18 6 L22 18 M30 6 L26 18" fill="none" strokeWidth="2.5" strokeLinecap="round" />
          </>
        ) : (
          <>
            <path d="M2 12 h44" fill="none" strokeWidth="2.5" strokeLinecap="round" />
            <circle cx="24" cy="12" r="4.5" fill="none" strokeWidth="2" />
          </>
        )}
      </svg>
    </div>
  );
}

function buildAria(links: ChainLink[], breakAt: number | null): string {
  if (breakAt === null) {
    return `Hash chain of ${links.length} sealed entries, intact.`;
  }
  return `Hash chain of ${links.length} entries. Chain broken at entry ${breakAt}; entries from there on are unverifiable.`;
}
