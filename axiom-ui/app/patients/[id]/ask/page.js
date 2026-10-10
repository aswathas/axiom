'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import AskScreen from '../../../../components/AskScreen';
import Shell, { useShell } from '../../../../components/Shell';
import { Notice } from '../../../../components/Chrome';

function PatientAskContent({ patientId }) {
  const { openSource, setActivePatientId } = useShell();

  useEffect(() => {
    if (patientId) {
      setActivePatientId(patientId);
    }
  }, [patientId, setActivePatientId]);

  if (!patientId) {
    return (
      <div style={{ marginTop: 24 }}>
        <h1 className="page">Ask</h1>
        <Notice tone="warn" title="NO PATIENT SPECIFIED">
          Please select a patient before issuing clinical inquiries.
          <div style={{ marginTop: 12 }}>
            <Link href="/patients" className="btn primary" style={{ textDecoration: 'none' }}>
              Return to Patients
            </Link>
          </div>
        </Notice>
      </div>
    );
  }

  return (
    <>
      <div style={{ marginTop: 18, marginBottom: 12 }}>
        <Link
          href={`/patients/${encodeURIComponent(patientId)}`}
          className="btn ghost"
          style={{ textDecoration: 'none', fontSize: 11, padding: '4px 8px' }}
        >
          ← Back to Patient Chart
        </Link>
      </div>

      <AskScreen patientId={patientId} onSource={openSource} />
    </>
  );
}

export default function PatientAskPage({ params }) {
  const routeParams = useParams();
  const rawId = params?.id || routeParams?.id;
  const patientId = rawId ? decodeURIComponent(rawId) : '';

  return (
    <Shell>
      <PatientAskContent patientId={patientId} />
    </Shell>
  );
}
