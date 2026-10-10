'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * One fetch-with-state hook so every screen has the same four states:
 * loading, loaded, offline, and failed.
 *
 * Racing requests are discarded — switching patients quickly must not let a
 * slow earlier response overwrite a fast later one and show the wrong chart.
 */
export function useResource(fetcher, deps = [], { skip = false } = {}) {
  const [state, setState] = useState({
    loading: !skip, data: null, error: null, offline: false, reason: null, isOffline: false,
  });
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce(n => n + 1), []);

  useEffect(() => {
    if (skip) {
      setState({ loading: false, data: null, error: null, offline: false, reason: null, isOffline: false });
      return undefined;
    }
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve()
      .then(fetcher)
      .then((res) => {
        if (!live) return;
        setState({
          loading: false,
          data: res ? res.data : null,
          error: null,
          offline: Boolean(res && res.offline),
          isOffline: Boolean(res && res.offline),
          reason: (res && res.offlineReason) || null,
        });
      })
      .catch((e) => {
        if (!live) return;
        setState({
          loading: false,
          data: null,
          error: e.message || String(e),
          offline: Boolean(e.isOffline),
          isOffline: Boolean(e.isOffline),
          reason: e.message || null,
        });
      });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce, skip]);

  return { ...state, reload };
}

/** Track an in-flight mutation (upload / ask) with its own error channel. */
export function useMutation() {
  const [state, setState] = useState({ pending: false, error: null, isOffline: false });

  const run = useCallback(async (fn) => {
    setState({ pending: true, error: null, isOffline: false });
    try {
      const out = await fn();
      setState({ pending: false, error: null, isOffline: false });
      return out;
    } catch (e) {
      setState({
        pending: false,
        error: e.message || String(e),
        isOffline: Boolean(e.isOffline),
      });
      return null;
    }
  }, []);

  const reset = useCallback(() => setState({ pending: false, error: null, isOffline: false }), []);

  return { ...state, run, reset };
}