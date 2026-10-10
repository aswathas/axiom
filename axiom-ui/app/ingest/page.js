'use client';

import UploadScreen from '../../components/UploadScreen';
import Shell, { useShell } from '../../components/Shell';

function IngestContent() {
  const { openSource } = useShell();
  return <UploadScreen onSource={openSource} />;
}

export default function IngestPage() {
  return (
    <Shell>
      <IngestContent />
    </Shell>
  );
}
