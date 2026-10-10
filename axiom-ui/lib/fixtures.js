/**
 * Benchmark prose constants.
 *
 * Synthetic clinical fixtures previously defined here have been removed.
 * AXIOM never serves invented clinical records when the backend is unreachable.
 * Transport failures and outages are surfaced loudly and honestly rather than
 * simulating a healthy backend with canned patients. Only the benchmark
 * limitations prose required by the evidence screen remains.
 */

export const FALLBACK_LIMITATIONS = [
  'Every figure on screen is derived from the live audit trail and graph; no canned patient data is served when the backend is offline.',
  'The robustness sweep and planted-truth accuracy figures require the Python benchmark harness (`python -m axiom.bench`) and are not derivable from the HTTP API alone.',
  'Claim calibration is only as good as the labelling set the calibrator was fit on; the shipped isotonic fit is a five-point curve, not a measured reliability diagram.',
];