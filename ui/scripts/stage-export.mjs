/**
 * Copy the static export into the Python package, at src/minilake/ui_static.
 *
 * That is where `app.py` looks first, and putting it inside the package is what
 * gets it into the wheel — `packages = ["src/minilake"]` already includes
 * everything under that directory. A `force-include` of `ui/out` would do the
 * same for a source checkout but breaks the editable install in the Docker image,
 * where `ui/` is not in the build context.
 *
 * No-op when there is no Python source tree above this directory, which is the
 * case inside the image's frontend-builder stage — there, the Dockerfile copies
 * the export across itself.
 */
import { cp, rm, stat } from "node:fs/promises";
import path from "node:path";

const source = path.join(process.cwd(), "out");
const packageDir = path.resolve(process.cwd(), "..", "src", "minilake");
const destination = path.join(packageDir, "ui_static");

async function isDirectory(target) {
  try {
    return (await stat(target)).isDirectory();
  } catch {
    return false;
  }
}

if (!(await isDirectory(source))) {
  console.error(`No export at ${source} — run \`next build\` first.`);
  process.exit(1);
}

if (!(await isDirectory(packageDir))) {
  console.log("No Python package alongside this app; leaving the export in ./out.");
  process.exit(0);
}

await rm(destination, { recursive: true, force: true });
await cp(source, destination, { recursive: true });

console.log(`Staged the export into ${path.relative(path.resolve(process.cwd(), ".."), destination)}`);
