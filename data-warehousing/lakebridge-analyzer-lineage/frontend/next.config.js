/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',  // Static HTML export for Databricks Apps
  distDir: '.next/out',  // Output to .next/out instead of default 'out'
  reactStrictMode: true,
  
  // Disable image optimization for static export
  images: {
    unoptimized: true,
  },
  
  // In Databricks Apps, FastAPI serves the static frontend
  // and handles API routing - no proxy needed
};

module.exports = nextConfig;




