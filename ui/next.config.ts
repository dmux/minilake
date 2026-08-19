import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The UI ships inside the minilake container and is served by FastAPI as plain
  // static files from /ui — there is no Node process at runtime.
  output: "export",
  basePath: "/ui",
  // Emit `out/<route>/index.html` rather than `out/<route>.html`, which is what
  // Starlette's StaticFiles(html=True) resolves for a directory request.
  trailingSlash: true,
};

export default nextConfig;
