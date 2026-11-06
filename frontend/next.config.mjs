// Forward /api/* to FastAPI so browser calls are same-origin and the
// httpOnly auth cookie works (plan D11).
const apiUrl = process.env.API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false, // no development badge on screen during demos
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
};

export default nextConfig;
