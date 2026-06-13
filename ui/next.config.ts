import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
    return [
      // Proxy all /api/* except SSE — SSE must connect directly to avoid Next.js buffering
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
