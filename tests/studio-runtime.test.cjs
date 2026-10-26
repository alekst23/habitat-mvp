const assert = require("node:assert/strict");
const { webcrypto } = require("node:crypto");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = resolve(__dirname, "..");
const source = readFileSync(resolve(root, "frontend/studio-runtime.js"), "utf8");
const nativeRequest = {
  input: [{ id: "user-1", kind: "input", type: "message", role: "user", status: "completed", content: [{ type: "text", text: "Chart costs by agent." }] }],
  instructions: "Use only the dashboard data.",
  tools: [{ name: "configure_widget", description: "Configure a dashboard widget", parameters: { type: "object", properties: {} } }],
  responseFormat: { type: "text" },
};

function adapterWith(fetch) {
  const scope = { crypto: webcrypto, DOMException, fetch };
  vm.runInNewContext(source, scope);
  return scope.HabitatStudioRuntime.createHabitatAdapter({ csrfToken: () => "test-csrf" });
}

test("a native turn transports authentication context once and emits matching text/tool events", async () => {
  const requests = [];
  const response = {
    id: "response-1", createdAt: 1, status: "completed", output: [
      { id: "message-1", kind: "output", type: "message", role: "assistant", status: "completed", content: [{ type: "text", text: "Adding the cost chart.", annotations: [] }] },
      { id: "item-1", kind: "output", type: "function_call", callId: "call-1", name: "configure_widget", arguments: '{"widgetId":"costs"}', status: "completed" },
    ],
  };
  const adapter = adapterWith(async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => response };
  });
  const controller = new AbortController();
  const turn = adapter.executeTurn(nativeRequest, { signal: controller.signal });
  const events = [];
  for await (const event of turn.stream) events.push(event);
  assert.equal(await turn.complete, response);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/audit/studio/ai");
  assert.equal(requests[0].options.credentials, "same-origin");
  assert.equal(requests[0].options.headers["X-CSRF-Token"], "test-csrf");
  assert.equal(requests[0].options.signal, controller.signal);
  const payload = JSON.parse(requests[0].options.body);
  assert.deepEqual(payload.request, nativeRequest);
  assert.match(payload.request_id, /^[0-9a-f]{8}-[0-9a-f-]{27}$/);
  assert.deepEqual(events.map(event => event.type), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END"]);
  assert.equal(events[1].delta, "Adding the cost chart.");
  assert.ok(events.slice(0, 3).every(event => event.messageId === "message-1"));
  assert.ok(events.slice(3).every(event => event.toolCallId === "call-1"));
  assert.equal(events[3].toolCallName, "configure_widget");
  assert.equal(events[4].delta, '{"widgetId":"costs"}');
});

test("failed, incomplete and rejected turns never expose tool calls or retry", async () => {
  for (const status of ["failed", "incomplete", "http-error"]) {
    let attempts = 0;
    const adapter = adapterWith(async () => {
      attempts += 1;
      return {
        ok: status !== "http-error",
        json: async () => ({ status, detail: "Assistant allowance exhausted", output: [{ type: "function_call", callId: "must-not-run", name: "configure_widget", arguments: "{}" }] }),
      };
    });
    const turn = adapter.executeTurn(nativeRequest);
    const events = [];
    await assert.rejects(async () => {
      for await (const event of turn.stream) events.push(event);
    });
    await assert.rejects(turn.complete);
    assert.equal(events.length, 0);
    assert.equal(attempts, 1);
  }
});

test("cancellation aborts the in-flight request without starting another billable turn", async () => {
  let attempts = 0;
  const adapter = adapterWith((url, options) => {
    attempts += 1;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    });
  });
  const controller = new AbortController();
  const turn = adapter.executeTurn(nativeRequest, { signal: controller.signal });
  controller.abort();
  await assert.rejects(turn.complete, { name: "AbortError" });
  await assert.rejects(async () => {
    for await (const event of turn.stream) assert.fail("Cancelled request emitted an event");
  }, { name: "AbortError" });
  assert.equal(attempts, 1);
});

test("served assets are the pinned official bundle, original licence and current adapter", () => {
  const vendor = resolve(root, "backend/aicl/web/static/vendor");
  assert.equal(JSON.parse(readFileSync(resolve(root, "node_modules/ag-studio/package.json"))).version, "3.0.0");
  assert.deepEqual(readFileSync(resolve(vendor, "ag-studio.min.js")), readFileSync(resolve(root, "node_modules/ag-studio/dist/umd/ag-studio.min.js")));
  assert.deepEqual(readFileSync(resolve(vendor, "ag-studio.LICENSE.html")), readFileSync(resolve(root, "node_modules/ag-studio/LICENSE.html")));
  assert.equal(readFileSync(resolve(vendor, "ag-studio-runtime.js"), "utf8"), source);
});
