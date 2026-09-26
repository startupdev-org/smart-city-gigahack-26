/** @type {import('next').NextConfig} */
const path = require("path");
const fs = require("fs");

// Force-read repo-root .env (ignore apps/web/.env.local entirely)
const repoRoot = path.join(__dirname, "../..");
const envPath = path.join(repoRoot, ".env");

function readRootEnv(filePath) {
  const out = {};
  if (!fs.existsSync(filePath)) return out;
  const text = fs.readFileSync(filePath, "utf8");
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq <= 0) continue;
    const key = line.slice(0, eq).trim();
    let val = line.slice(eq + 1).trim();
    if (
      (val.startsWith('"') && val.endsWith('"')) ||
      (val.startsWith("'") && val.endsWith("'"))
    ) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

const rootEnv = readRootEnv(envPath);
for (const [k, v] of Object.entries(rootEnv)) {
  process.env[k] = v;
}

const apiUrl = (process.env.NEXT_PUBLIC_API_URL || "").trim().replace(/\/$/, "");
if (!apiUrl) {
  console.warn(
    "[civic-ai] NEXT_PUBLIC_API_URL missing in repo-root .env — API calls will be same-origin /api"
  );
} else {
  console.info(`[civic-ai] API base from root .env → ${apiUrl}`);
}

const nextConfig = {
  reactStrictMode: true,
  outputFileTracingRoot: path.join(__dirname),
  allowedDevOrigins: ["127.0.0.1", "localhost", "civicai.visio.md"],
  env: {
    NEXT_PUBLIC_API_URL: apiUrl,
  },
  async rewrites() {
    if (!apiUrl) return [];
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
