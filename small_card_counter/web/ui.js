// Minimal UI: render only the "cards left in deck" counter.
const $ = (id) => document.getElementById(id);

let liveOnce = false;

// Window auto-resize: after each render we ask the OS window to match the
// natural content height. Width stays fixed; the user can drag the window.
const FIXED_WIDTH = 260;
let lastResizeH = -1;
let resizePending = false;

function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    // Use the body's scroll height — captures titlebar + content padding.
    const h = Math.max(40, Math.min(800, Math.ceil(document.body.scrollHeight)));
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize(FIXED_WIDTH, h); } catch (_) {}
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
    if (a[1] !== b[1]) return a[1] - b[1];   // low first
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

// Titlebar buttons (just quit; window is always on top, drag works always)
window.addEventListener('DOMContentLoaded', () => {
  $('btn-quit').addEventListener('click', async () => {
    try { await window.pywebview.api.quit(); } catch (_) {}
  });
  // Initial fit after first paint.
  setTimeout(fitWindowToContent, 50);
});

// ── Window dragging via the title bar ────────────────────────────────────────
// WebView2 ignores -webkit-app-region, so move the native window ourselves:
// on titlebar mousedown record the grab offset within the window, then on each
// mousemove move the window so the cursor keeps that same offset. Moves are
// coalesced to one per animation frame to keep the JS↔Python bridge light.
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
    if (a) a.move(x, y);
  }

  bar.addEventListener('mousedown', (e) => {
    if (e.target.closest('.tbtn')) return;     // ignore button clicks
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
