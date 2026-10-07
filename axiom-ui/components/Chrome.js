'use client';

/**
 * Small shared primitives. Deliberately not a design system — just the pieces
 * more than one screen needs, so the copy stays identical across them.
 */

export function Chip({ kind = 'mute', children }) {
  return <span className={`chip ${kind}`}>{children}</span>;
}

export function Spinner({ label }) {
  return (
    <div className="loading-row" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function LoadingCards({ n = 3, label = 'Loading' }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span style={{ position: 'absolute', left: -9999 }}>{label}…</span>
      {Array.from({ length: n }, (_, i) => <div key={i} className="skeleton" />)}
    </div>
  );
}

/**
 * A notice about the app's own state — backend down, malformed input.
 * The ONLY red surface in the app. A refusal must never use this.
 */
export function Notice({ tone = 'warn', title, children, action }) {
  return (
    <div className={`notice ${tone === 'error' ? 'err' : ''}`} role={tone === 'error' ? 'alert' : 'status'}>
      <div style={{ flex: 1 }}>
        <div className="notice-t">{title}</div>
        <div className="notice-b">{children}</div>
      </div>
      {action}
    </div>
  );
}

/**
 * Backend-unreachable banner.
 *
 * The demo runs two processes and one of them may legitimately be down, so
 * this states exactly which one and how to start it — a blank screen teaches a
 * judge nothing, and an empty patient list reads as "the product has no data".
 */
export function OfflineNotice({ api, onRetry, reason }) {
  return (
    <Notice
      tone="warn"
      title="BACKEND NOT REACHABLE — SHOWING INLINE FALLBACK DATA"
      action={
        onRetry && (
          <button type="button" className="btn" onClick={onRetry}>Retry</button>
        )
      }
    >
      Nothing below came from the API. Everything on screen is the built-in
      synthetic dataset, so the interface is demonstrable without a second
      process. Start the backend with{' '}
      <code>uvicorn api.main:app --port 8000</code> and press Retry.
      {reason ? <><br />Last error: {reason}</> : null}
      <br /><span style={{ color: 'var(--gold-dim)' }}>API base: {api}</span>
    </Notice>
  );
}
