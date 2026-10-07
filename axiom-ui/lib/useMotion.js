'use client';

import { useEffect, useState } from 'react';

/**
 * Live `prefers-reduced-motion`, not a build-time guess.
 *
 * Recharts animates series in by drawing the path left-to-right over ~1.5s.
 * That is motion with no informational content, so when the user has asked
 * for reduced motion the animation is switched off entirely rather than
 * merely shortened — a chart that sweeps in from the left is exactly the kind
 * of thing the setting exists to suppress.
 */
export function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReduced(mq.matches);
    const onChange = (e) => setReduced(e.matches);
    // Safari < 14 only has the deprecated API.
    if (mq.addEventListener) {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, []);

  return reduced;
}