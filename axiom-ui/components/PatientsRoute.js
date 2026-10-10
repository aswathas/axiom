'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { listPatients } from '../lib/api';
import PatientList from './PatientList';
import { Notice } from './Chrome';
import { useShell } from './Shell';

export default function PatientsRoute() {
  const router = useRouter();
  const { setActivePatientId } = useShell();
  const [patients, setPatients] = useState({
    loading: true,
    rows: [],
    offline: false,
    reason: null,
    error: null,
  });
  const [nonce, setNonce] = useState(0);

  const refresh = useCallback(() => {
    setPatients((s) => ({ ...s, loading: true, error: null }));
    listPatients()
      .then((r) =>
        setPatients({
          loading: false,
          rows: Array.isArray(r.data) ? r.data : [],
          offline: Boolean(r.offline),
          reason: r.offlineReason || null,
          error: null,
        })
      )
      .catch((e) =>
        setPatients({
          loading: false,
          rows: [],
          offline: false,
          reason: null,
          error: e.message || 'Failed to load patients',
        })
      );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, nonce]);

  const handleOpen = useCallback(
    (id) => {
      setActivePatientId(id);
      router.push(`/patients/${encodeURIComponent(id)}`);
    },
    [router, setActivePatientId]
  );

  const handleCreated = useCallback(
    (created) => {
      setNonce((n) => n + 1);
      if (created?.id) {
        setActivePatientId(created.id);
        router.push(`/patients/${encodeURIComponent(created.id)}`);
      }
    },
    [router, setActivePatientId]
  );

  return (
    <>
      {patients.error && (
        <Notice tone="error" title="PATIENT LIST FAILED">
          {patients.error}
          <div style={{ marginTop: 8 }}>
            <button
              type="button"
              className="btn"
              onClick={() => setNonce((n) => n + 1)}
            >
              Try again
            </button>
          </div>
        </Notice>
      )}

      <PatientList
        state={patients}
        onOpen={handleOpen}
        onRetry={() => setNonce((n) => n + 1)}
        onCreated={handleCreated}
      />
    </>
  );
}
