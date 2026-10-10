'use client';

import BenchmarkScreen from '../../components/BenchmarkScreen';
import { FALLBACK_LIMITATIONS } from '../../lib/fixtures';
import Shell, { useShell } from '../../components/Shell';

function EvidenceContent() {
  const { activePatientId } = useShell();
  return (
    <BenchmarkScreen
      patientId={activePatientId}
      limitations={FALLBACK_LIMITATIONS}
    />
  );
}

export default function EvidencePage() {
  return (
    <Shell>
      <EvidenceContent />
    </Shell>
  );
}
