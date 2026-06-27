// Counter window (companion to the main damage/board window). The Python
// side pushes the same view-model to both windows via window.onState; here
// we render only the deck counter list. Auto-sizes height to fit content.
const $ = (id) => document.getElementById(id);

let liveOnce = false;
const FIXED_WIDTH = 260;
let lastResizeH = -1;
let resizePending = false;
let currentUiScale = 1.0;  // updated by the bottom-right drag handle

// Latest state, so the hand-only toggle can re-render without a new push.
let lastRemaining = {};
let lastHandKeys = [];     // canonical counter keys of cards currently in hand
let handOnly = false;      // collapse view: show only the cards in hand

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

function rowHtml(name, n, inHand) {
  const cls = `counter-row${n === 0 ? ' zero' : n <= 2 ? ' low' : ''}${inHand ? ' in-hand' : ''}`;
  return `<div class="${cls}"><span class="counter-name">${name}</span><span class="counter-count">${n}</span></div>`;
}

function renderCounter() {
  const el = $('counter-list');
  const remaining = lastRemaining;
  if (!remaining || !Object.keys(remaining).length) {
    el.innerHTML = '<span class="empty-note">no cards in hand yet</span>';
    fitWindowToContent();
    return;
  }
  const handSet = new Set(lastHandKeys);
  // Ascending by copies-left, then by name (zh) — same order as before.
  const byCountThenName = (a, b) =>
    (a[1] !== b[1] ? a[1] - b[1] : a[0].localeCompare(b[0], 'zh-Hans-CN'));

  const entries = Object.entries(remaining);
  const inHand = entries.filter(([name]) => handSet.has(name)).sort(byCountThenName);

  if (handOnly) {
    // Collapsed view: only the cards currently in hand.
    el.innerHTML = inHand.length
      ? inHand.map(([name, n]) => rowHtml(name, n, true)).join('')
      : '<span class="empty-note">手里没有可计数的牌</span>';
    fitWindowToContent();
    return;
  }

  // Full view: hand cards pinned on top (highlighted), a divider, then the rest.
  const rest = entries.filter(([name]) => !handSet.has(name)).sort(byCountThenName);
  const parts = inHand.map(([name, n]) => rowHtml(name, n, true));
  if (inHand.length && rest.length) parts.push('<div class="counter-divider"></div>');
  parts.push(...rest.map(([name, n]) => rowHtml(name, n, false)));
  el.innerHTML = parts.join('');
  fitWindowToContent();
}

// ── Diagnostic status banner ──────────────────────────────────────────────
// Python pushes problems here (game not found, frida blocked by AV, engine
// download failed, …) so the user sees WHY the counter is empty instead of a
// silent blank window. Keyed by id so each notice updates in place.
const _statusNotices = {};

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function renderStatus() {
  const el = $('status-banner');
  if (!el) return;  // DOM not ready yet — DOMContentLoaded will call us again
  const items = Object.values(_statusNotices);
  if (!items.length) {
    el.className = 'status-banner hidden';
    el.innerHTML = '';
    lastResizeH = -1;
    fitWindowToContent();
    return;
  }
  // Most severe first so the worst problem is on top.
  const order = { error: 0, warn: 1, info: 2 };
  items.sort((a, b) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
  el.className = 'status-banner ' + (items[0].level || 'info');
  el.innerHTML = items.map((it) =>
    `<div class="status-item ${it.level || 'info'}">` +
      `<div class="status-text">${escapeHtml(it.text)}</div>` +
      (it.detail ? `<div class="status-detail">${escapeHtml(it.detail)}</div>` : '') +
    `</div>`
  ).join('');
  lastResizeH = -1;  // banner changed height — force a re-fit
  fitWindowToContent();
}

window.onStatus = function (s) {
  if (!s || !s.id) return;
  if (s.clear || (!s.text && !s.detail)) {
    delete _statusNotices[s.id];
  } else {
    _statusNotices[s.id] = s;
  }
  renderStatus();
};

window.onState = function (vm) {
  if (!liveOnce) {
    liveOnce = true;
    $('status-dot').classList.add('live');
  }
  if (vm && vm.round) {
    $('round-pill').textContent = `R${vm.round}`;
  }
  lastRemaining = (vm && vm.counter && vm.counter.remaining) || {};
  const hand = (vm && vm.me && Array.isArray(vm.me.hand)) ? vm.me.hand : [];
  // counterKey is the canonical name the Python side keys `remaining` by.
  lastHandKeys = hand
    .filter((c) => c && typeof c === 'object')
    .map((c) => c.counterKey || c.name)
    .filter(Boolean);
  renderCounter();
};

function applyHandOnly(on, persist) {
  handOnly = !!on;
  const btn = $('btn-hand-only');
  if (btn) btn.classList.toggle('active', handOnly);
  lastResizeH = -1;  // force a resize: the list height changed
  renderCounter();
  if (persist) {
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      a.set_setting('counterHandOnly', handOnly).catch(() => {});
    }
  }
}

window.addEventListener('DOMContentLoaded', () => {
  $('btn-quit').addEventListener('click', async () => {
    try { await window.pywebview.api.quit(); } catch (_) {}
  });
  $('btn-hand-only').addEventListener('click', () => applyHandOnly(!handOnly, true));
  // 复盘 (Review) — opens the review window (moved here from the main window,
  // which is hidden in counter-only mode).
  const rev = $('btn-review');
  if (rev) rev.addEventListener('click', async () => {
    const a = window.pywebview && window.pywebview.api;
    if (a && a.open_review) { try { await a.open_review(); } catch (e) { console.error(e); } }
  });
  // Render any status notice that arrived before the DOM was ready.
  renderStatus();
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
      applyHandOnly(s.counterHandOnly === true, false);
    } catch (_) {}
  }
  // Pull any diagnostic notice raised during startup (before this page was
  // ready) so the user still sees why the counter might be empty.
  if (a && a.get_pending_status) {
    try {
      const pending = await a.get_pending_status();
      if (Array.isArray(pending)) pending.forEach((n) => window.onStatus(n));
    } catch (_) {}
  }
});
