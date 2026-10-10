'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { API } from '../lib/api';
import * as api from '../lib/api';
import { Chip, LoadingCards, Notice, OfflineNotice } from './Chrome';

// createPatient is expected from lib/api.js per Contract 5 addition.
// Guarded against missing export so Next.js builds cleanly before other worker lands it.
const createPatient = api['createPatient'];

/**
 * Scene 01 / Patient Registry — `GET /api/patients`.
 *
 * Full clinical registry surface:
 * - Real-time search/filter by name, MRN, and patient ID
 * - Registration action for new patients with inline error handling
 * - Clear primary "Open Chart" action on every patient card
 * - Honest actionable empty and error states guiding the clinician to next steps
 */
export default function PatientList({ state, onOpen, onRetry, onCreated }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [showNewForm, setShowNewForm] = useState(false);
  const [mrn, setMrn] = useState('');
  const [name, setName] = useState('');
  const [dob, setDob] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  const filteredRows = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const rows = state?.rows || [];
    if (!q) return rows;
    return rows.filter((p) => {
      const pName = (p.name || '').toLowerCase();
      const pMrn = (p.mrn || '').toLowerCase();
      const pId = (p.id || '').toLowerCase();
      return pName.includes(q) || pMrn.includes(q) || pId.includes(q);
    });
  }, [state?.rows, searchQuery]);

  const handleCreate = async (e) => {
    e.preventDefault();
    const cleanMrn = mrn.trim();
    if (!cleanMrn) {
      setFormError('MRN is required.');
      return;
    }

    setSubmitting(true);
    setFormError(null);

    try {
      if (typeof createPatient !== 'function') {
        throw new Error(
          'Patient creation API (createPatient) is pending export in lib/api.js.'
        );
      }
      const created = await createPatient({
        mrn: cleanMrn,
        name: name.trim(),
        dob: dob.trim(),
      });

      setMrn('');
      setName('');
      setDob('');
      setShowNewForm(false);

      if (onCreated) {
        onCreated(created);
      } else if (created?.id && onOpen) {
        onOpen(created.id);
      }
    } catch (err) {
      // 4xx or ApiError caught and displayed inline in the form
      setFormError(err.message || 'Failed to create patient record.');
    } finally {
      setSubmitting(false);
    }
  };

  if (state.loading) {
    return (
      <>
        <h1 className="page">Patients</h1>
        <p className="lede">Reading the case list from the AXIOM store.</p>
        <LoadingCards n={3} label="Loading patients" />
      </>
    );
  }

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h1 className="page" style={{ margin: '26px 0 6px' }}>Patients</h1>
          <p className="lede">
            Every record is reconstructed from uploaded documents into a typed,
            time-stamped graph. Click a patient to open the chart.
          </p>
        </div>
        <div style={{ marginTop: 26 }}>
          <button
            type="button"
            className="btn primary"
            onClick={() => {
              setShowNewForm(!showNewForm);
              setFormError(null);
            }}
            aria-expanded={showNewForm}
          >
            {showNewForm ? '✕ Close Form' : '+ New Patient'}
          </button>
        </div>
      </div>

      {state.offline && (
        <OfflineNotice api={API} onRetry={onRetry} reason={state.reason} />
      )}

      {/* New Patient Registration Panel */}
      {showNewForm && (
        <div className="card" style={{ marginTop: 20, borderLeft: '4px solid var(--gold)' }} role="region" aria-label="Register New Patient">
          <div className="card-title">
            <span>REGISTER NEW PATIENT</span>
            <button
              type="button"
              className="btn ghost"
              onClick={() => {
                setShowNewForm(false);
                setFormError(null);
              }}
              style={{ fontSize: 11, padding: '3px 8px' }}
            >
              Cancel
            </button>
          </div>
          <form onSubmit={handleCreate}>
            <div className="field" style={{ marginTop: 8 }}>
              <label htmlFor="reg-mrn">Medical Record Number (MRN) *</label>
              <input
                id="reg-mrn"
                type="text"
                required
                placeholder="e.g. MRN-90210"
                value={mrn}
                onChange={(e) => setMrn(e.target.value)}
                disabled={submitting}
              />
              <div className="hint">Required. Unique clinical identifier across records.</div>
            </div>

            <div className="field">
              <label htmlFor="reg-name">Patient Full Name</label>
              <input
                id="reg-name"
                type="text"
                placeholder="e.g. Jane Doe"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={submitting}
              />
            </div>

            <div className="field">
              <label htmlFor="reg-dob">Date of Birth</label>
              <input
                id="reg-dob"
                type="date"
                value={dob}
                onChange={(e) => setDob(e.target.value)}
                disabled={submitting}
              />
            </div>

            {formError && (
              <div style={{ marginTop: 14 }}>
                <Notice tone="error" title="REGISTRATION FAILED">
                  {formError}
                </Notice>
              </div>
            )}

            <div className="toolbar" style={{ marginTop: 18 }}>
              <button
                type="submit"
                className="btn primary"
                disabled={submitting || !mrn.trim()}
              >
                {submitting ? 'Creating record…' : 'Register Patient'}
              </button>
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setShowNewForm(false);
                  setFormError(null);
                }}
                disabled={submitting}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Registry Search / Filter Bar */}
      <div className="toolbar" style={{ marginTop: 22, display: 'flex', gap: 12, alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 260 }}>
          <input
            type="text"
            className="field"
            style={{
              width: '100%',
              padding: '9px 12px',
              border: '1px solid var(--line)',
              borderRadius: 5,
              fontSize: 13,
              fontFamily: 'inherit',
              background: 'var(--white)',
              color: 'var(--ink)',
              margin: 0,
            }}
            placeholder="Search patients by name or MRN…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Filter patient list"
          />
        </div>
        {searchQuery && (
          <button
            type="button"
            className="btn ghost"
            onClick={() => setSearchQuery('')}
            style={{ fontSize: 12 }}
          >
            Clear filter
          </button>
        )}
      </div>

      {/* Patient Cards Grid */}
      <div className="pt-grid">
        {filteredRows.map((p) => {
          const empty = Number(p.node_count) === 0;
          return (
            <div
              key={p.id}
              className="pt-card"
              onClick={() => onOpen(p.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onOpen(p.id);
                }
              }}
              aria-label={`Open chart for ${p.name || p.id}, MRN ${p.mrn || 'none'}`}
            >
              <div className="pt-card-name">{p.name || p.id}</div>
              <div className="pt-card-dem">
                DOB {p.dob || '—'} · {p.mrn || 'no MRN'}
              </div>
              <div style={{ marginTop: 9, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Chip kind="info">{p.doc_count ?? 0} documents</Chip>
                <Chip kind={empty ? 'mute' : 'ok'}>
                  {p.node_count ?? 0} graph nodes
                </Chip>
                {empty && <Chip kind="mute">no provenance yet</Chip>}
              </div>
              <div className="pt-card-stats" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div className="stat-l">id</div>
                  <div className="pt-card-dem">{p.id}</div>
                </div>
                <button
                  type="button"
                  className="btn primary"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpen(p.id);
                  }}
                  style={{ fontSize: 11, padding: '6px 12px' }}
                >
                  Open Chart →
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Filter Yielded Zero Matches */}
      {filteredRows.length === 0 && state.rows.length > 0 && (
        <div className="card" style={{ marginTop: 20, textAlign: 'center', padding: '30px 20px' }}>
          <div style={{ fontSize: 13, color: 'var(--grey-d)', marginBottom: 12 }}>
            No patients match &ldquo;<strong>{searchQuery}</strong>&rdquo;.
          </div>
          <button type="button" className="btn" onClick={() => setSearchQuery('')}>
            Clear Search Filter
          </button>
        </div>
      )}

      {/* Genuine Empty State (0 patients in store) */}
      {state.rows.length === 0 && (
        <div className="card" style={{ marginTop: 24, textAlign: 'center', padding: '38px 24px' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--gold-dim)', letterSpacing: '1.2px', marginBottom: 8 }}>
            PATIENT REGISTRY
          </div>
          <h2 style={{ fontSize: 19, fontWeight: 700, margin: '0 0 10px', color: 'var(--ink)' }}>
            No Patients in the Store
          </h2>
          <p style={{ color: 'var(--grey-d)', fontSize: 13.5, lineHeight: 1.6, maxWidth: 540, margin: '0 auto 24px' }}>
            {state.offline
              ? 'The backend is unreachable and no fallback patient records were returned. You can register a new patient now or proceed to document ingest once the API is online.'
              : 'The backend responded successfully with an empty patient store. To begin clinical workflows, register a new patient or ingest medical records.'}
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn primary"
              onClick={() => {
                setShowNewForm(true);
                setFormError(null);
              }}
            >
              + Register New Patient
            </button>
            <Link href="/ingest" className="btn" style={{ textDecoration: 'none' }}>
              Ingest Documents →
            </Link>
          </div>
        </div>
      )}
    </>
  );
}