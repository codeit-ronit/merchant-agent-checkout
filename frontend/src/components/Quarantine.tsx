import type { ReactNode } from 'react';

// The proxy wraps untrusted (model-visible, attacker-influenceable) content in a
// per-run nonce delimiter: ⟦UNTRUSTED::…⟧. The operator must see at a glance
// which parts of the context were untrusted, so we split any string on that
// marker and render the enclosed spans as unmistakable quarantine blocks.
const OPEN = '⟦UNTRUSTED';
const MARKER_RE = /⟦UNTRUSTED(?:::|:[^⟧]*::)?([\s\S]*?)⟧/g;

export function containsUntrusted(text: string): boolean {
  return typeof text === 'string' && text.includes(OPEN);
}

// Splits text into trusted plain segments and quarantined segments.
export function renderWithQuarantine(text: string): ReactNode {
  if (!containsUntrusted(text)) return text;
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  MARKER_RE.lastIndex = 0;
  let i = 0;
  while ((m = MARKER_RE.exec(text)) !== null) {
    if (m.index > last) out.push(<span key={`t${i}`}>{text.slice(last, m.index)}</span>);
    out.push(<QuarantineInline key={`q${i}`}>{m[1]}</QuarantineInline>);
    last = m.index + m[0].length;
    i += 1;
  }
  if (last < text.length) out.push(<span key="tail">{text.slice(last)}</span>);
  return <>{out}</>;
}

function QuarantineInline({ children }: { children: ReactNode }) {
  return (
    <span className="quarantine-inline" title="Untrusted content — quarantined by the proxy">
      <span className="quarantine-tag" aria-hidden="true">
        ⚠ UNTRUSTED
      </span>
      <span className="quarantine-inline-body">{children}</span>
    </span>
  );
}

// A full-width quarantine callout for the run trace (a quarantine_applied event).
export function QuarantineBlock({ fields, note }: { fields?: string[]; note?: string }) {
  return (
    <div className="quarantine-block" role="note">
      <div className="quarantine-block-head">
        <span className="quarantine-tag" aria-hidden="true">
          ⚠ UNTRUSTED
        </span>
        <span className="quarantine-block-title">Content quarantined before the model saw it</span>
      </div>
      <p className="quarantine-block-body">
        {note ??
          'These fields carried attacker-influenceable text. They were wrapped in a per-run nonce delimiter so the model cannot mistake them for instructions.'}
      </p>
      {fields && fields.length > 0 ? (
        <ul className="quarantine-fields">
          {fields.map((f) => (
            <li key={f} className="mono">
              {f}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
