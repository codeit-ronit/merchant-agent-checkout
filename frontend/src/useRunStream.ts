import { useCallback, useEffect, useRef, useState } from 'react';
import { runStreamUrl } from './api';
import type { TraceEvent } from './types';

export type StreamStatus = 'idle' | 'streaming' | 'done' | 'error';

export interface StreamState {
  events: TraceEvent[];
  status: StreamStatus;
  lastSequence: number;
  reconnect: () => void;
}

// Live trace via SSE. The server replays a run's events named `trace`, then a
// `done` event. We dedupe by sequence number so a dropped connection can
// reconnect and backfill without gaps or duplicates. `seed` renders the trace
// the POST already returned if EventSource is unavailable.
export function useRunStream(runId: string | null, seed?: TraceEvent[]): StreamState {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>('idle');
  const seenRef = useRef<Set<number>>(new Set());
  const esRef = useRef<EventSource | null>(null);
  const doneRef = useRef(false);
  const [nonce, setNonce] = useState(0);

  const reconnect = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setStatus('idle');
      seenRef.current = new Set();
      doneRef.current = false;
      return;
    }

    // Fresh run: reset dedupe set only when the run id changes (nonce reconnect
    // keeps the set so already-rendered events are skipped on replay).
    if (nonce === 0) {
      seenRef.current = new Set();
      setEvents([]);
      doneRef.current = false;
    }
    setStatus('streaming');

    if (typeof EventSource === 'undefined') {
      // No SSE in this environment — render the seed trace we already have.
      if (seed) {
        setEvents(seed);
      }
      setStatus('done');
      return;
    }

    const es = new EventSource(runStreamUrl(runId));
    esRef.current = es;

    const onTrace = (e: MessageEvent) => {
      try {
        const evt = JSON.parse(e.data) as TraceEvent;
        if (seenRef.current.has(evt.sequence)) return; // backfill dedupe
        seenRef.current.add(evt.sequence);
        setEvents((prev) => [...prev, evt].sort((a, b) => a.sequence - b.sequence));
      } catch {
        /* ignore a malformed frame; the next one carries a higher sequence */
      }
    };

    const onDone = () => {
      doneRef.current = true;
      setStatus('done');
      es.close();
    };

    const onError = () => {
      if (doneRef.current) return;
      // EventSource auto-reconnects; if it has given up (CLOSED) fall back to the
      // seed trace so the operator still sees the full run.
      if (es.readyState === EventSource.CLOSED) {
        if (seed) {
          seed.forEach((evt) => {
            if (!seenRef.current.has(evt.sequence)) seenRef.current.add(evt.sequence);
          });
          setEvents((prev) => {
            const merged = [...prev];
            seed.forEach((evt) => {
              if (!merged.some((m) => m.sequence === evt.sequence)) merged.push(evt);
            });
            return merged.sort((a, b) => a.sequence - b.sequence);
          });
          setStatus('done');
        } else {
          setStatus('error');
        }
      }
    };

    es.addEventListener('trace', onTrace as EventListener);
    es.addEventListener('done', onDone as EventListener);
    es.addEventListener('error', onError as EventListener);

    return () => {
      es.removeEventListener('trace', onTrace as EventListener);
      es.removeEventListener('done', onDone as EventListener);
      es.removeEventListener('error', onError as EventListener);
      es.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, nonce]);

  const lastSequence = events.length ? events[events.length - 1].sequence : -1;
  return { events, status, lastSequence, reconnect };
}
