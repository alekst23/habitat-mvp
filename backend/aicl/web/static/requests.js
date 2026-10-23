"use strict";

// Suggested answers only fill the visible field; the owner still submits it.
document.querySelectorAll("[data-request-answer]").forEach((button) => {
  button.setAttribute("aria-pressed", "false");
  button.addEventListener("click", () => {
    const answer = document.getElementById(button.getAttribute("aria-controls"));
    if (!answer) return;
    answer.value = button.dataset.requestAnswer;
    document.querySelectorAll("[data-request-answer]").forEach((choice) => {
      choice.setAttribute("aria-pressed", String(choice === button));
    });
    answer.focus();
  });
});

const answer = document.getElementById("request-answer");
if (answer) {
  answer.addEventListener("input", () => {
    document.querySelectorAll("[data-request-answer]").forEach((button) => {
      button.setAttribute("aria-pressed", String(answer.value === button.dataset.requestAnswer));
    });
  });
}
