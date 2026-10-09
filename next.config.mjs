/** @type {import('next').NextConfig} */
const nextConfig = {
  // Verification can use a fresh output directory while the dev server stays open.
  distDir: process.env.NEXT_BUILD_DIR || ".next",
};

export default nextConfig;
