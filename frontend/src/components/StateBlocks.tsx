import type { ReactNode } from 'react';
import type { ApiError } from '../api';
import { UNREACHABLE_HINT } from '../api';

export function PageHeader({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        <h1 className="page-title">{title}</h1>
        <p className="page-lede">{lede}</p>
      </div>
      {children ? <div className="page-header-aside">{children}</div> : null}
    </div>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state-block state-loading" role="status" aria-live="polite">
      <span className="state-spinner" aria-hidden="true" />
      <span className="state-title">{label}</span>
    </div>
  );
}

// Error states explain what happened and what to do next — they never apologise
// and are never vague. A network failure gets the definite "run make demo" hint.
export function ErrorState({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  const isNetwork = error.kind === 'network';
  return (
    <div className="state-block state-error" role="alert">
      <span className="state-icon" aria-hidden="true">
        ⚠
      </span>
      <div className="state-body">
        <h2 className="state-title">
          {isNetwork ? 'Control plane not reachable' : 'That request did not complete'}
        </h2>
        <p className="state-detail">{isNetwork ? UNREACHABLE_HINT : error.message}</p>
        {isNetwork ? (
          <p className="state-hint">
            Start the offline demo, then retry — no credentials or network are required.
          </p>
        ) : null}
      </div>
      {onRetry ? (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

// Empty states are invitations to act, not dead ends.
export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: ReactNode;
}) {
  return (
    <div className="state-block state-empty">
      <span className="state-icon" aria-hidden="true">
        ⬡
      </span>
      <div className="state-body">
        <h2 className="state-title">{title}</h2>
        <p className="state-detail">{detail}</p>
      </div>
      {action ? <div className="state-action">{action}</div> : null}
    </div>
  );
}
