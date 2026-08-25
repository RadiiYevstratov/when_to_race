/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    // Schedule pages are server-rendered per request so the viewer's timezone
    // cookie is honoured on first paint.
    staleTimes: { dynamic: 0 },
  },
};

export default nextConfig;
