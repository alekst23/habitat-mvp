/* A count only: no secret data or responses are sent through notifications. */
(() => {
  const badges = document.querySelectorAll('[data-request-count]');
  if (!badges.length) return;
  let timer;
  async function refresh() {
    if (document.hidden) return;
    try {
      const response = await fetch('/requests/summary', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || response.redirected) return;
      const {pending_count: count} = await response.json();
      if (!Number.isSafeInteger(count) || count < 0) return;
      badges.forEach(badge => {
        badge.textContent = String(count);
        badge.hidden = count === 0;
        badge.setAttribute('aria-label', `${count} requests need your response`);
      });
    } catch (_) { /* Keep the last known count during interrupted connections. */ }
  }
  refresh();
  timer = window.setInterval(refresh, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('pagehide', () => window.clearInterval(timer), {once: true});
})();
