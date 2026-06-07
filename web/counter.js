// Counter window (companion to the main damage/board window). The Python
// side pushes the same view-model to both windows via window.onState; here
// we render only the deck counter list. Auto-sizes height to fit content.
const $ = (id) => document.getElementById(id);

let liveOnce = false;
const FIXED_WIDTH = 260;
let lastResizeH = -1;
let resizePending = false;
let currentUiScale = 1.0;  // updated by the bottom-right drag handle

function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    const rawH = Math.ceil(document.body.scrollHeight);
    const h = Math.max(40, Math.min(1200, Math.round(rawH * currentUiScale)));
    const w = Math.round(FIXED_WIDTH * currentUiScale);
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize_counter(w, h); } catch (_) {}
    }
  });
}

function renderCounter(remaining) {
  const el = $('counter-list');
  if (!remaining || !Object.keys(remaining).length) {
    el.innerHTML = '<span class="empty-note">no cards in hand yet</span>';
    fitWindowToContent();
    return;
  }
  const sorted = Object.entries(remaining).sort((a, b) => {
    if (a[1] !== b[1]) return a[1] - b[1];
    return a[0].localeCompare(b[0], 'zh-Hans-CN');
  });
  el.innerHTML = sorted.map(([name, n]) => {
    const cls = n === 0 ? 'zero' : n <= 2 ? 'low' : '';
    return `<div class="counter-row ${cls}"><span class="counter-name">${name}</span><span class="counter-count">${n}</span></div>`;
  }).join('');
  fitWindowToContent();
}

window.onState = function (vm) {
  if (!liveOnce) {
    liveOnce = true;
    $('status-dot').classList.add('live');
  }
  if (vm && vm.round) {
    $('round-pill').textContent = `R${vm.round}`;
  }
  const remaining = (vm && vm.counter && vm.counter.remaining) || {};
  renderCounter(remaining);
};

window.addEventListener('DOMContentLoaded', () => {
  $('btn-quit').addEventListener('click', async () => {
    try { await window.pywebview.api.quit(); } catch (_) {}
  });
  setTimeout(fitWindowToContent, 50);
});

// Window dragging via the title bar (same approach as the main window).
(function setupDrag() {
  const bar = $('titlebar');
  if (!bar) return;
  let dragging = false;
  let grabX = 0, grabY = 0;
  let pending = null, rafId = 0;

  function flush() {
    rafId = 0;
    if (!pending) return;
    const { x, y } = pending;
    pending = null;
    const a = window.pywebview && window.pywebview.api;
    if (a) a.move_counter(x, y);
  }

  bar.addEventListener('mousedown', (e) => {
    if (e.target.closest('.tbtn')) return;
    if (e.button !== 0) return;
    dragging = true;
    grabX = e.clientX;
    grabY = e.clientY;
    e.preventDefault();
  });

  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    pending = { x: Math.round(e.screenX - grabX), y: Math.round(e.screenY - grabY) };
    if (!rafId) rafId = requestAnimationFrame(flush);
  });

  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Bottom-right resize handle (CSS zoom + window resize) ──────────────
// Mirrors the main window's resize-handle behavior. Scale is persisted as
// `counterScale` in the shared settings so the two windows track their own
// preferred sizes independently.
(function setupResize() {
  const handle = $('resize-handle');
  if (!handle) return;
  const MIN_SCALE = 0.6, MAX_SCALE = 2.5;
  const SENSITIVITY = 250;
  let uiScale = 1.0;

  function applyScale(s) {
    s = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    uiScale = s;
    currentUiScale = s;
    document.body.style.zoom = String(s);
    lastResizeH = -1;
    fitWindowToContent();
    return s;
  }
  window.applyCounterScale = applyScale;

  let dragging = false, startX = 0, startY = 0, startScale = 1;
  handle.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    startX = e.screenX;
    startY = e.screenY;
    startScale = uiScale;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    const delta = (dx + dy) / 2 / SENSITIVITY;
    applyScale(startScale + delta);
  });
  window.addEventListener('mouseup', async () => {
    if (!dragging) return;
    dragging = false;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      try { await a.set_setting('counterScale', uiScale); } catch (_) {}
    }
  });
  window.addEventListener('blur', () => { dragging = false; });
})();

// Load and apply the persisted counter scale on startup.
window.addEventListener('pywebviewready', async () => {
  const a = window.pywebview && window.pywebview.api;
  if (a && a.get_settings && typeof window.applyCounterScale === 'function') {
    try {
      const s = await a.get_settings();
      window.applyCounterScale(Number(s.counterScale) || 1.0);
    } catch (_) {}
  }
});
