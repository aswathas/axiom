/** @type {import('next').NextConfig} */

// The backend's CORS allowlist is fixed at http://localhost:3000 and
// http://127.0.0.1:3000 (api/main.py). Next's dev server silently falls
// forward to 3001, 3002, ... when 3000 is busy, and then every browser call
// fails on CORS while the backend is demonstrably up — a failure that looks
// exactly like "the backend is down" and wastes demo time.
//
// So the browser talks to same-origin /api/* and Next proxies to the backend.
// Set NEXT_PUBLIC_API_DIRECT=1 to bypass the proxy and call the API directly
// (useful when you are serving the built bundle from the same origin as the
// API, or debugging CORS itself).
const upstream = process.env.NEXT_PUBLIC_API || 'http://localhost:8000';
const direct = process.env.NEXT_PUBLIC_API_DIRECT === '1';

const nextConfig = {
  reactStrictMode: true,
  ...(direct
    ? {}
    : {
        async rewrites() {
          return [{ source: '/api/:path*', destination: `${upstream}/api/:path*` }];
        },
      }),
};

module.exports = nextConfig;