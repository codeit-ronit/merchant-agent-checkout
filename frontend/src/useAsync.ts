import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: ApiError | null;
  reload: () => void;
}

// Small loader hook shared by every view. Runs `fn` on mount and whenever the
// `deps` change; exposes an explicit reload. Never throws to render — the error
// is captured so each view can show its definite error state.
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const mounted = useRef(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableFn = useCallback(fn, deps);

  const run = useCallback(() => {
    setLoading(true);
    setError(null);
    stableFn()
      .then((v) => {
        if (mounted.current) setData(v);
      })
      .catch((e) => {
        if (!mounted.current) return;
        setError(e instanceof ApiError ? e : new ApiError('network', String(e)));
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  }, [stableFn]);

  useEffect(() => {
    mounted.current = true;
    run();
    return () => {
      mounted.current = false;
    };
  }, [run]);

  return { data, loading, error, reload: run };
}
