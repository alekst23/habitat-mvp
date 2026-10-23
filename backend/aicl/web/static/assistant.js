(function () {
  "use strict";
  var root = document.querySelector("[data-owner-assistant]");
  if (!root) return;
  var message = document.getElementById("assistant-message");
  var messageForm = root.querySelector('[data-assistant-submit="message"]');
  root.querySelectorAll("[data-assistant-example]").forEach(function (button) {
    button.addEventListener("click", function () {
      message.value = button.dataset.assistantExample;
      message.focus();
      message.setSelectionRange(message.value.length, message.value.length);
    });
  });
  root.querySelectorAll("[data-assistant-revise]").forEach(function (link) {
    link.addEventListener("click", function () { message.focus(); });
  });
  message.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault();
      messageForm.requestSubmit();
    }
  });
  var forms = root.querySelectorAll("[data-assistant-submit]");
  forms.forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (root.dataset.submitting === "true") { event.preventDefault(); return; }
      root.dataset.submitting = "true";
      form.setAttribute("aria-busy", "true");
      forms.forEach(function (other) {
        other.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = true; });
      });
      // Keep successful form fields enabled so ordinary browser submission works.
      message.readOnly = true;
      form.querySelector("[data-assistant-request-status]").textContent =
        form.dataset.assistantSubmit === "message" ? "Working on your message…" : "Applying your confirmed proposal…";
    });
  });
  window.addEventListener("pageshow", function () {
    delete root.dataset.submitting;
    message.readOnly = false;
    forms.forEach(function (form) {
      form.removeAttribute("aria-busy");
      form.querySelectorAll('button[type="submit"]').forEach(function (button) { button.disabled = false; });
      form.querySelector("[data-assistant-request-status]").textContent = "";
    });
  });
  var transcript = root.querySelector("[data-assistant-transcript]");
  if (transcript.querySelector(".assistant-messages")) transcript.scrollTop = transcript.scrollHeight;
})();
