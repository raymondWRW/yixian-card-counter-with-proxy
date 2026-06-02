// Counter window (companion to the main damage/board window). The Python
// side pushes the same view-model to both windows via window.onState; here
// we render only the deck counter list. Auto-sizes height to fit content.
const $ = (id) => document.getElementById(id);

let liveOnce = false;
const FIXED_WIDTH = 260;
let lastResizeH = -1;
let resizePending = false;

function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    const h = Math.max(40, Math.min(800, Math.ceil(document.body.scrollHeight)));
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize_counter(FIXED_WIDTH, h); } catch (_) {}
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
