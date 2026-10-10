'use client';

import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { API, getHealth, listPatients } from '../lib/api';
import SourceDrawer from './SourceDrawer';

const ShellContext = createContext(null);

export function useShell() {
  const ctx = useContext(ShellContext);
  if (!ctx) {
    throw new Error('useShell must be used within a ShellProvider');
  }
  return ctx;
}

const NAV_ITEMS = [
  { id: 'patients', category: 'REGISTRY', label: 'Patients' },
  { id: 'chart', category: 'RECORD', label: 'Chart' },
  { id: 'ask', category: 'INQUIRY', label: 'Ask' },
  { id: 'ingest', category: 'INTAKE', label: 'Ingest', href: '/ingest' },
  { id: 'evidence', category: 'AUDIT', label: 'Evidence', href: '/evidence' },
];

function getActiveNav(pathname) {
  if (!pathname || pathname === '/' || pathname === '/patients') return 'patients';
  if (pathname.startsWith('/patients/') && pathname.endsWith('/ask')) return 'ask';
  if (pathname.startsWith('/patients/')) return 'chart';
  if (pathname.startsWith('/ingest')) return 'ingest';
  if (pathname.startsWith('/evidence')) return 'evidence';
  return '';
}

export default function Shell({ children }) {
  const pathname = usePathname();
  const [activePatientId, setActivePatientId] = useState(null);
  const [health, setHealth] = useState({ data: null, offline: true });
  const [sourceTarget, setSourceTarget] = useState(null);

  const refreshHealth = useCallback(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth({ data: null, offline: true }));
  }, []);

  useEffect(() => {
    refreshHealth();
  }, [refreshHealth]);

  // Keep active patient synced with URL if present
  useEffect(() => {
    if (!pathname) return;
    const match = pathname.match(/^\/patients\/([^/]+)/);
    if (match && match[1] && match[1] !== 'new') {
      setActivePatientId(decodeURIComponent(match[1]));
    }
  }, [pathname]);

  // If no patient is selected, default to the first available patient in the database
  useEffect(() => {
    if (!activePatientId) {
      listPatients()
        .then((res) => {
          if (res?.data && Array.isArray(res.data) && res.data.length > 0) {
            setActivePatientId(res.data[0].id);
          }
        })
        .catch(() => {});
    }
  }, [activePatientId]);

  const openSource = useCallback((target) => {
    setSourceTarget(target);
  }, []);

  const closeSource = useCallback(() => {
    setSourceTarget(null);
  }, []);

  const activeNav = getActiveNav(pathname || '');

  const boundary =
    'AXIOM DOES NOT DIAGNOSE AND DOES NOT PRESCRIBE. IT SUMMARISES A RECORD YOU ALREADY HOLD.';

  return (
    <ShellContext.Provider
      value={{
        activePatientId,
        setActivePatientId,
        sourceTarget,
        openSource,
        closeSource,
        health,
        refreshHealth,
      }}
    >
      <header className="topbar">
        <div className="topbar-inner">
          <div>
            <Link href="/patients" style={{ textDecoration: 'none', color: 'inherit' }}>
              <div className="brand">AXIOM</div>
              <div className="brand-sub">AI-NATIVE CLINICAL ASSISTANCE</div>
            </Link>
          </div>
          <div className="topbar-meta">
            <div>{health.data ? `API ${health.data.llm || 'none'}` : 'API …'}</div>
            <div style={{ color: health.offline ? '#d9a441' : '#6e6e6e' }}>
              {health.offline ? 'fallback data' : 'live · ' + API.replace(/^https?:\/\//, '')}
            </div>
          </div>
        </div>
      </header>

      {/* Permanent and non-dismissible scope boundary */}
      <div className="boundary" role="note" aria-label="Scope boundary">
        {boundary}
      </div>

      <main className="shell">
        <nav className="nav" aria-label="Clinical navigation">
          {NAV_ITEMS.map((item) => {
            const isActive = activeNav === item.id;
            let targetHref = item.href || '/patients';
            if (item.id === 'patients') {
              targetHref = '/patients';
            } else if (item.id === 'chart') {
              targetHref = activePatientId
                ? `/patients/${encodeURIComponent(activePatientId)}`
                : '/patients';
            } else if (item.id === 'ask') {
              targetHref = activePatientId
                ? `/patients/${encodeURIComponent(activePatientId)}/ask`
                : '/patients';
            }

            return (
              <Link
                key={item.id}
                href={targetHref}
                className={`navbtn ${isActive ? 'active' : ''}`}
                aria-current={isActive ? 'page' : undefined}
                style={{ textDecoration: 'none', color: 'inherit' }}
              >
                <span className="navbtn-t">{item.category}</span>
                <span className="navbtn-n">{item.label}</span>
              </Link>
            );
          })}
        </nav>

        {children}
      </main>

      {sourceTarget && (
        <SourceDrawer target={sourceTarget} onClose={closeSource} />
      )}
    </ShellContext.Provider>
  );
}
