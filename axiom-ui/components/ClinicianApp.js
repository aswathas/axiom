'use client';

import PatientsRoute from './PatientsRoute';

/**
 * Replaced single-useState screen switcher with real Next.js App Router shell
 * and URL-based navigation.
 * Retained for backwards compatibility with any callers expecting default export.
 */
export default function ClinicianApp() {
  return <PatientsRoute />;
}