/* Habitat's transport adapter for the official AG Studio Agent Framework.
 * Rebuild the served copy with `npm run build:studio` after editing this file.
 * The server owns provider credentials, model choice, cost limits and idempotency.
 */
(function (global) {
  "use strict";

  function createHabitatAdapter(options = {}) {
    const endpoint = options.endpoint || "/audit/studio/ai";
    if (typeof endpoint !== "string" || !endpoint.startsWith("/") || endpoint.startsWith("//") || endpoint.includes("\\")) {
      throw new Error("The Studio assistant endpoint must be on this application's origin.");
    }

    return {
      executeTurn(request, turnOptions = {}) {
        const csrfToken = typeof options.csrfToken === "function" ? options.csrfToken() : options.csrfToken;
        const requestId = global.crypto.randomUUID();
        const complete = global.fetch(endpoint, {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken || "" },
          signal: turnOptions.signal,
          body: JSON.stringify({ request_id: requestId, request }),
        }).then(async (response) => {
          const body = await response.json();
          if (!response.ok) {
            const detail = typeof body.detail === "string" ? body.detail : body.message;
            throw new Error(detail || "The Studio assistant request could not be completed.");
          }
          // Never allow a truncated turn to execute partially generated dashboard tools.
          if (body.status !== "completed" || !Array.isArray(body.output)) {
            throw new Error(body.error?.message || "The Studio assistant stopped before finishing this turn.");
          }
          return body;
        });
        // The harness consumes the stream first and then complete. Mark rejection handled
        // now while retaining the original rejecting promise for both consumers.
        complete.catch(() => {});

        return {
          complete,
          stream: {
            async *[Symbol.asyncIterator]() {
              const response = await complete;
              for (const item of response.output) {
                if (turnOptions.signal?.aborted) {
                  throw turnOptions.signal.reason || new DOMException("Aborted", "AbortError");
                }
                if (item.type === "message") {
                  yield { type: "TEXT_MESSAGE_START", messageId: item.id, role: "assistant" };
                  for (const part of item.content || []) {
                    const text = part.type === "text" ? part.text : part.type === "refusal" ? part.refusal : "";
                    if (text) yield { type: "TEXT_MESSAGE_CONTENT", messageId: item.id, delta: text };
                  }
                  yield { type: "TEXT_MESSAGE_END", messageId: item.id };
                } else if (item.type === "function_call") {
                  yield { type: "TOOL_CALL_START", toolCallId: item.callId, toolCallName: item.name };
                  yield { type: "TOOL_CALL_ARGS", toolCallId: item.callId, delta: item.arguments };
                  yield { type: "TOOL_CALL_END", toolCallId: item.callId };
                } else if (item.type === "reasoning" && item.summary?.length) {
                  yield { type: "REASONING_MESSAGE_START", messageId: item.id };
                  for (const part of item.summary) {
                    yield { type: "REASONING_MESSAGE_CONTENT", messageId: item.id, delta: part.text };
                  }
                  yield { type: "REASONING_MESSAGE_END", messageId: item.id };
                }
              }
            },
          },
        };
      },
    };
  }

  global.HabitatStudioRuntime = Object.freeze({ createHabitatAdapter });
})(globalThis);
