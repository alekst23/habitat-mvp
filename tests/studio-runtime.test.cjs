const assert = require("node:assert/strict");
const { existsSync, readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");

const root = resolve(__dirname, "..");
const vendor = resolve(root, "backend/aicl/web/static/vendor");

test("served assets remain the pinned official bundle and original licence", () => {
  assert.equal(JSON.parse(readFileSync(resolve(root, "node_modules/ag-studio/package.json"))).version, "3.0.0");
  assert.deepEqual(readFileSync(resolve(vendor, "ag-studio.min.js")), readFileSync(resolve(root, "node_modules/ag-studio/dist/umd/ag-studio.min.js")));
  assert.deepEqual(readFileSync(resolve(vendor, "ag-studio.LICENSE.html")), readFileSync(resolve(root, "node_modules/ag-studio/LICENSE.html")));
});

test("the retired model adapter is neither shipped nor retained as source", () => {
  assert.equal(existsSync(resolve(vendor, "ag-studio-runtime.js")), false);
  assert.equal(existsSync(resolve(root, "frontend/studio-runtime.js")), false);
});
