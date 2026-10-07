'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { API, getHealth, listPatients } from '../lib/api';
import { FALLBACK_LIMITATIONS } from '../lib/fixtures';
import PatientList from './PatientList';
import ChartScreen from './ChartScreen';
import AskScreen from './AskScreen';
import UploadScreen from './UploadScreen';
import BenchmarkScreen from './BenchmarkScreen';
import SourceDrawer from './SourceDrawer';
import { Notice } from './Chrome';

const SCREENS = [
  { id: 'patients', beat: '01', name: 'Patients' },
  { id: 'chart', beat: '02', name: 'Chart' },
  { id: 'ask', beat: '03', name: 'Ask' },
  { id: 'upload', beat: '04', name: 'Ingest' },
  { id: 'bench', beat: '05', name: 'Evidence' },
];

/**
 * Shell + routing. No data fetching of its own beyond the patient list and the
 * health probe, so every screen owns its own loading and error states.
 *
 * The previous build took a single pre-baked `fixture` prop describing one
 * patient and five scripted "scenes". Everything downstream of that was real
 * UI over invented data. This version keeps the visual language — the topbar,
 * the palette, the card system, the chips — and replaces the data with the
 * live API.
 */
export default function ClinicianApp() {
  const [screen, setScreen] = useState('patients');
  const [patientId, setPatientId] = useState(null);
  const [patients, setPatients] = useState({ loading: true, rows: [], offline: false, error: null });
  const [health, setHealth] = useState({ data: null, offline: true });
  const [nonce, setNonce] = useState(0);
  const [sourceTarget, setSourceTarget] = useState(null);

  const refresh = useCallback(() => {
    setPatients({ loading: true, rows: [], offline: false, error: null });
    getHealth().then(setHealth);
    listPatients()
      .then((r) => setPatients({
        loading: false,
        rows: Array.isArray(r.data) ? r.data : [],
        offline: r.offline,
        reason: r.offlineReason,
        error: null,
      }))
      .catch((e) => setPatients({ loading: false, rows: [], offline: false, error: e.message }));
  }, []);

  useEffect(() => { refresh(); }, [refresh, nonce]);

  // Land on the first patient automatically so the chart/ask screens are never
  // a dead end on a one-patient demo database.
  useEffect(() => {
    if (!patientId && patients.rows.length) setPatientId(patients.rows[0].id);
  }, [patients.rows, patientId]);

  const go = useCallback((id) => {
    setScreen(id);
    if (id !== 'patients' && !patientId && patients.rows.length) {
      setPatientId(patients.rows[0].id);
    }
  }, [patientId, patients.rows]);

  const openPatient = useCallback((id) => {
    setPatientId(id);
    setScreen('chart');
  }, []);

  const boundary = 'AXIOM DOES NOT DIAGNOSE AND DOES NOT PRESCRIBE. IT SUMMARISES A RECORD YOU ALREADY HOLD.';

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div>
            <div className="brand">AXIOM</div>
            <div className="brand-sub">AI-NATIVE CLINICAL ASSISTANCE</div>
          </div>
          <div className="topbar-meta">
            <div>{health.data ? `API ${health.data.llm || 'none'}` : 'API …'}</div>
            <div style={{ color: health.offline ? '#d9a441' : '#6e6e6e' }}>
              {health.offline ? 'fallback data' : 'live · ' + API.replace(/^https?:\/\//, '')}
            </div>
          </div>
        </div>
      </header>

      {/* Permanent and non-dismissible by construction: rendered outside the
          interactive regions, with no close control anywhere in the app. */}
      <div className="boundary" role="note" aria-label="Scope boundary">{boundary}</div>

      <main className="shell">
        <nav className="nav" aria-label="Screens">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`navbtn ${screen === s.id ? 'active' : ''}`}
              aria-current={screen === s.id ? 'page' : undefined}
              onClick={() => go(s.id)}
            >
              <span className="navbtn-t">SCENE {s.beat}</span>
              <span className="navbtn-n">{s.name}</span>
            </button>
          ))}
        </nav>

        {patients.error && (
          <Notice tone="error" title="PATIENT LIST FAILED">
            {patients.error}
            <div style={{ marginTop: 8 }}>
              <button type="button" className="btn" onClick={() => setNonce(n => n + 1)}>
                Try again
              </button>
            </div>
          </Notice>
        )}

        {screen === 'patients' && (
          <PatientList
            state={patients}
            onOpen={openPatient}
            onRetry={() => setNonce(n => n + 1)}
          />
        )}

        {screen === 'chart' && (
          <ChartScreen
            patientId={patientId}
            onAsk={() => setScreen('ask')}
            onSource={(t) => setSourceTarget(t)}
          />
        )}

        {screen === 'ask' && (
          <AskScreen patientId={patientId} onSource={(t) => setSourceTarget(t)} />
        )}

        {screen === 'upload' && <UploadScreen onSource={(t) => setSourceTarget(t)} />}

        {screen === 'bench' && (
          <BenchmarkScreen patientId={patientId} limitations={FALLBACK_LIMITATIONS} />
        )}
      </main>

      {/* One drawer for the whole app. Every citation button on every screen
          opens the same thing, so "two clicks to source" is one behaviour
          rather than five. */}
      {sourceTarget && (
        <SourceDrawer
          target={sourceTarget}
          onClose={() => setSourceTarget(null)}
        />
      )}
    </>
  );
}