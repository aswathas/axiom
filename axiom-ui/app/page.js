import ClinicianApp from '../components/ClinicianApp';
import fixture from '../public/fixture.json';

export default function Page() {
  return <ClinicianApp fixture={fixture} />;
}