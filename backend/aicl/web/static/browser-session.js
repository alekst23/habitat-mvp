"use strict";

// This is an owner-only relay. It never stores, logs or records typed input.
(() => {
  const root = document.querySelector("[data-browser-session]");
  if (!root || root.dataset.active !== "true") return;
  const canvas = document.getElementById("browser-screen");
  const context = canvas.getContext("2d");
  const overlay = document.getElementById("browser-overlay");
  const error = document.getElementById("browser-error");
  const status = document.getElementById("browser-frame-status");
  const finish = document.getElementById("browser-complete");
  let stopped = false, fetching = false, ready = false, pending = 0;
  let inputQueue = Promise.resolve();

  async function call(action, body) {
    const response = await fetch(`${root.dataset.endpoint}/${action}`, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"X-CSRF-Token": root.dataset.csrf, "Content-Type": "application/json"},
      body: JSON.stringify(body || {}),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.message || "The browser is unavailable. Return to the request to reconnect.");
    return result;
  }

  function fail(message) {
    stopped = true;
    ready = false;
    error.textContent = message;
    error.hidden = false;
    status.textContent = "Disconnected";
    overlay.textContent = "Browser disconnected. Your job stays paused.";
    overlay.hidden = false;
    canvas.style.visibility = "hidden";
    document.getElementById("browser-return").disabled = true;
  }

  async function frame() {
    if (stopped || fetching || pending || document.hidden) return;
    fetching = true;
    try {
      const result = await call("frame");
      if (stopped) return;
      const bitmap = new Image();
      bitmap.src = `data:image/jpeg;base64,${result.image}`;
      await bitmap.decode();
      canvas.width = result.width;
      canvas.height = result.height;
      context.drawImage(bitmap, 0, 0);
      // The broker exposes origin only, never callback query strings or tokens.
      document.getElementById("browser-origin").textContent = result.domain || result.origin || result.url || "Website unavailable";
      overlay.hidden = true;
      canvas.style.visibility = "visible";
      status.textContent = "Live";
      ready = true;
    } catch (failure) {
      fail(failure.message);
    } finally { fetching = false; }
  }

  function input(payload) {
    if (!ready || stopped) return;
    pending += 1;
    inputQueue = inputQueue.then(async () => {
      if (!stopped) await call("input", payload);
    }).catch((failure) => fail(failure.message)).finally(() => { pending -= 1; });
  }

  canvas.addEventListener("click", (event) => {
    if (!ready || stopped) return;
    const rect = canvas.getBoundingClientRect();
    input({type: "click", x: Math.min(canvas.width - 1, Math.max(0, Math.round((event.clientX - rect.left) * canvas.width / rect.width))),
      y: Math.min(canvas.height - 1, Math.max(0, Math.round((event.clientY - rect.top) * canvas.height / rect.height)))});
    canvas.focus({preventScroll: true});
  });
  canvas.addEventListener("keydown", (event) => {
    if (event.isComposing) return;
    if (event.key === "Escape") {
      event.preventDefault();
      document.getElementById("browser-cancel").focus();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") return; // Native paste event below.
    event.preventDefault();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
      input({type: "key", key: "ControlOrMeta+A"});
    } else if (!event.ctrlKey && !event.metaKey && !event.altKey && event.key.length === 1) {
      input({type: "text", text: event.key});
    } else if (["Backspace", "Delete", "Enter", "Tab", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"].includes(event.key)) {
      input({type: "key", key: (event.shiftKey ? "Shift+" : "") + event.key});
    }
  });
  // Native text entry and IMEs may emit beforeinput without printable keydown.
  // Prevent the edit: no password text is retained in this document's DOM.
  canvas.addEventListener("beforeinput", (event) => {
    event.preventDefault();
    if (event.inputType === "insertText" && event.data) input({type: "text", text: event.data});
  });
  canvas.addEventListener("paste", (event) => {
    event.preventDefault();
    const value = event.clipboardData.getData("text/plain");
    if (value.length > 4000) { error.textContent = "Paste up to 4,000 characters at a time."; error.hidden = false; return; }
    input({type: "text", text: value});
  });
  canvas.addEventListener("wheel", (event) => {
    if (!ready || stopped) return;
    event.preventDefault();
    input({type: "scroll", delta_y: Math.round(Math.max(-720, Math.min(720, event.deltaY)))});
  }, {passive: false});

  document.getElementById("browser-refresh").addEventListener("click", frame);
  finish.addEventListener("submit", async (event) => {
    event.preventDefault();
    await inputQueue;
    if (stopped) return;
    stopped = true;
    canvas.style.visibility = "hidden";
    document.getElementById("browser-return").disabled = true;
    status.textContent = "Returning session…";
    finish.submit();
  });
  const expiry = document.getElementById("browser-expiry");
  const endsAt = Date.parse(expiry.dateTime);
  const timer = window.setInterval(() => {
    if (stopped) { window.clearInterval(timer); return; }
    const seconds = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
    if (Number.isFinite(seconds)) {
      expiry.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} remaining`;
      if (seconds === 0) { fail("This sign-in session expired. Start a new one from the request."); return; }
    }
    frame();
  }, 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { canvas.style.visibility = "hidden"; ready = false; }
    else frame();
  });
  window.addEventListener("pagehide", () => {
    stopped = true;
    window.clearInterval(timer);
    context.clearRect(0, 0, canvas.width, canvas.height);
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload(); // Revalidate the lease after back/forward cache restoration.
  });
  frame();
})();
