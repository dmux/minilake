/**
 * Copy Monaco's AMD build into public/ so the editor is served by minilake.
 *
 * @monaco-editor/react loads Monaco from jsDelivr by default. minilake's image is
 * deliberately offline-capable — DuckDB extensions and Spark jars are baked in at
 * build time — so a CDN dependency would put the SQL editor, the main thing the UI
 * is for, behind an internet connection.
 *
 * Invoked explicitly from the `dev` and `build` scripts rather than via a `prebuild`
 * hook: pre/post lifecycle scripts are not run by every package manager, and a
 * silently skipped copy produces an image whose editor 404s.
 */
import { cp, mkdir, rm, stat } from "node:fs/promises";
import path from "node:path";

async function exists(target) {
  try {
    await stat(target);
    return true;
  } catch {
    return false;
  }
}

// Resolved by walking node_modules rather than with require.resolve: the package's
// exports map rewrites every subpath to ./esm/vs/*, so the AMD build under min/vs —
// the one @monaco-editor/react's loader wants — is unreachable through it.
async function findMonacoVs(startDir) {
  let dir = startDir;
  for (;;) {
    const candidate = path.join(dir, "node_modules", "monaco-editor", "min", "vs");
    if (await exists(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

const source = await findMonacoVs(process.cwd());
const destination = path.join(process.cwd(), "public", "monaco", "vs");

if (!source) {
  console.error("monaco-editor/min/vs not found — is the dependency installed?");
  process.exit(1);
}

await rm(destination, { recursive: true, force: true });
await mkdir(path.dirname(destination), { recursive: true });
await cp(source, destination, { recursive: true });

console.log(`Copied Monaco to ${path.relative(process.cwd(), destination)}`);
