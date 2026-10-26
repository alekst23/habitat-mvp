import { copyFile, mkdir, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// AG publishes a self-contained browser bundle, including its chart/grid dependencies.
// Copy it byte-for-byte: no CDN dependency, framework migration or generated shim.
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const studioPackage = resolve(root, "node_modules/ag-studio");
const manifest = JSON.parse(await readFile(resolve(studioPackage, "package.json"), "utf8"));
if (manifest.version !== "3.0.0") {
  throw new Error(`Expected pinned ag-studio 3.0.0; found ${manifest.version}`);
}

const vendor = resolve(root, "backend/aicl/web/static/vendor");
await mkdir(vendor, { recursive: true });
await copyFile(resolve(studioPackage, "dist/umd/ag-studio.min.js"), resolve(vendor, "ag-studio.min.js"));
await copyFile(resolve(studioPackage, "LICENSE.html"), resolve(vendor, "ag-studio.LICENSE.html"));
await copyFile(resolve(root, "frontend/studio-runtime.js"), resolve(vendor, "ag-studio-runtime.js"));
console.log("Copied official AG Studio 3.0.0 browser bundle, licence, and Habitat adapter.");
