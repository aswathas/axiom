'use client';

import Link from 'next/link';
import Shell from '../components/Shell';

export default function NotFound() {
  return (
    <Shell>
      <div className="card" style={{ marginTop: 28, textAlign: 'center', padding: '42px 24px' }}>
        <div
          style={{
            fontSize: 11,
            fontWeight: 800,
            color: 'var(--crit)',
            letterSpacing: '1.2px',
            marginBottom: 8,
          }}
        >
          404 — NOT FOUND
        </div>
        <h1 className="page" style={{ margin: '0 0 10px', fontSize: 22 }}>
          Resource or Screen Not Found
        </h1>
        <p className="lede" style={{ maxWidth: 520, margin: '0 auto 24px', fontSize: 13.5 }}>
          The clinical route, patient record, or document view you requested does not exist or has been moved.
        </p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
          <Link href="/patients" className="btn primary" style={{ textDecoration: 'none' }}>
            Return to Patients
          </Link>
        </div>
      </div>
    </Shell>
  );
}
