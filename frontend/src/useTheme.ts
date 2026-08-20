import { useCallback, useEffect, useState } from 'react';

export type ThemeChoice = 'light' | 'dark' | 'system';

const KEY = 'sentinel-theme';

function readStored(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    if (v === 'light' || v === 'dark') return v;
  } catch {
    /* ignore */
  }
  return 'system';
}

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', choice);
  }
}

// Manual theme toggle. 'system' defers to prefers-color-scheme; 'light'/'dark'
// stamp data-theme on <html> and override the media query in both directions.
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(readStored);

  useEffect(() => {
    apply(choice);
    try {
      if (choice === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      /* ignore */
    }
  }, [choice]);

  const cycle = useCallback(() => {
    setChoice((c) => (c === 'system' ? 'light' : c === 'light' ? 'dark' : 'system'));
  }, []);

  return { choice, setChoice, cycle };
}
