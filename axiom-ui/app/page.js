import ClinicianApp from '../components/ClinicianApp';

// No fixture is imported here any more. The app reads the live API (Contract 5)
// through lib/api.js, which falls back to inline synthetic data only when the
// backend is unreachable — and says so on screen when it does.
export default function Page() {
  return <ClinicianApp />;
}