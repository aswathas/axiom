'use client';

import { useEffect } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import ChartScreen from '../../../components/ChartScreen';
import Shell, { useShell } from '../../../components/Shell';
import { Notice } from '../../../components/Chrome';

function PatientChartContent({ patientId }) {
  const router = useRouter();
  const { openSource, setActivePatientId } = useShell();

  useEffect(() => {
    if (patientId) {
      setActivePatientId(patientId);
    }
  }, [patientId, setActivePatientId]);

  if (!patientId) {
    return (
      <div style={{ marginTop: 24 }}>
        <h1 className="page">Chart</h1>
        <Notice tone="warn" title="NO PATIENT SPECIFIED">
          Please select a patient from the patient registry.
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
          href="/patients"
          className="btn ghost"
          style={{ textDecoration: 'none', fontSize: 11, padding: '4px 8px' }}
        >
          ← Back to Patients
        </Link>
      </div>

      <ChartScreen
        patientId={patientId}
        onAsk={() => router.push(`/patients/${encodeURIComponent(patientId)}/ask`)}
        onSource={openSource}
      />
    </>
  );
}

export default function PatientChartPage({ params }) {
  const routeParams = useParams();
  const rawId = params?.id || routeParams?.id;
  const patientId = rawId ? decodeURIComponent(rawId) : '';

  return (
    <Shell>
      <PatientChartContent patientId={patientId} />
    </Shell>
  );
}
