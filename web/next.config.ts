import type { NextConfig } from 'next';

// When SENTINEL_API_ORIGIN is set (for example https://sentinel-api.onrender.com),
// the dashboard proxies /sentinel-api/* to the backend. Browser calls then stay
// same-origin, so the backend's SameSite=strict session cookies keep working.
const apiOrigin = process.env.SENTINEL_API_ORIGIN?.replace(/\/$/, '');

const nextConfig: NextConfig = {
  async rewrites() {
    return apiOrigin
      ? [{ source: '/sentinel-api/:path*', destination: `${apiOrigin}/:path*` }]
      : [];
  },
};

export default nextConfig;
