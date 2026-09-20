import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: false,
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      { source: "/backend/:path*", destination: `${api}/:path*` },
    ];
  },
};

export default nextConfig;
