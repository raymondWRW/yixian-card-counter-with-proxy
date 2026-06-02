// Minimal UI: render only the "cards left in deck" counter.
const $ = (id) => document.getElementById(id);

let liveOnce = false;

// ── Language toggle ─────────────────────────────────────────────────────────
// Default = Chinese. Persists in localStorage so user preference survives
// across launches. UI labels (title, empty notes, tooltips) and card names
// are translated when the user toggles. Card-name translations come from
// card_names.js (window.CN_TO_EN_CARDS), generated from yisim's names.json.
const UI_STRINGS = {
  cn: {
    title: '剩余卡牌',
    waiting: '等待游戏…',
    noCards: '手牌为空',
    quitTip: '退出',
    langToggleTip: '切换语言 / Toggle language',
    langButton: '中',
  },
  en: {
    title: 'Cards Left',
    waiting: 'waiting for game…',
    noCards: 'no cards in hand yet',
    quitTip: 'Quit',
    langToggleTip: '切换语言 / Toggle language',
    langButton: 'EN',
  },
};
const LANG_STORAGE_KEY = 'yxlite.lang';
let lang = (function () {
  try {
    const saved = localStorage.getItem(LANG_STORAGE_KEY);
    return saved === 'en' ? 'en' : 'cn';   // default cn
  } catch (_) { return 'cn'; }
})();

// Translate a single card name CN → EN. Handles the paired-transform format
// "天谕·攻/守" by treating it as a slash-joined pair: look up the first face
// "天谕·攻" + look up the synthetic second face "天谕·守" and join the English
// outputs with "/". Falls back to the original CN name if no mapping found.
function translateCardName(cn) {
  if (lang !== 'en') return cn;
  const map = window.CN_TO_EN_CARDS || {};
  // Paired transform: A·X/Y → translate "A·X" + "A·Y", join EN parts.
  const slashIdx = cn.lastIndexOf('/');
  const dotIdx = cn.lastIndexOf('·');
  if (slashIdx > dotIdx && dotIdx > 0) {
    const prefix = cn.slice(0, dotIdx + 1);    // "天谕·"
    const a = cn.slice(dotIdx + 1, slashIdx);  // "攻"
    const b = cn.slice(slashIdx + 1);          // "守"
    const enA = map[prefix + a];
    const enB = map[prefix + b];
    if (enA && enB) {
      // Strip the redundant prefix from B: "Heavenly Decree - X" / "Y"
      const dashIdx = enB.lastIndexOf(' - ');
      const bTail = dashIdx >= 0 ? enB.slice(dashIdx + 3) : enB;
      return `${enA}/${bTail}`;
    }
  }
  return map[cn] || cn;
}

function applyUiLanguage() {
  const s = UI_STRINGS[lang];
  $('ui-title').textContent = s.title;
  const emptyEl = $('ui-empty');
  if (emptyEl) emptyEl.textContent = s.waiting;
  const btnLang = $('btn-lang');
  if (btnLang) {
    btnLang.textContent = s.langButton;
    btnLang.title = s.langToggleTip;
  }
  const btnQuit = $('btn-quit');
  if (btnQuit) btnQuit.title = s.quitTip;
  document.documentElement.lang = lang === 'en' ? 'en' : 'zh-Hans';
}

function toggleLanguage() {
  lang = lang === 'cn' ? 'en' : 'cn';
  try { localStorage.setItem(LANG_STORAGE_KEY, lang); } catch (_) {}
  applyUiLanguage();
  // Re-render the counter with new language.
  renderCounter(lastRemaining);
}

// Window auto-resize: after each render we ask the OS window to match the
// natural content height. Width stays fixed; the user can drag the window.
const FIXED_WIDTH = 260;
let lastResizeH = -1;
let resizePending = false;
let lastRemaining = null;

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
  lastRemaining = remaining;
  const el = $('counter-list');
  const s = UI_STRINGS[lang];
  if (!remaining || !Object.keys(remaining).length) {
    el.innerHTML = `<span class="empty-note">${liveOnce ? s.noCards : s.waiting}</span>`;
    fitWindowToContent();
    return;
  }
  // Sort by count first (low → high), then by translated name for stability.
  const collator = lang === 'en' ? 'en' : 'zh-Hans-CN';
  const sorted = Object.entries(remaining)
    .map(([name, n]) => [translateCardName(name), n])
    .sort((a, b) => {
      if (a[1] !== b[1]) return a[1] - b[1];
      return a[0].localeCompare(b[0], collator);
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
  applyUiLanguage();
  $('btn-quit').addEventListener('click', async () => {
    try { await window.pywebview.api.quit(); } catch (_) {}
  });
  $('btn-lang').addEventListener('click', toggleLanguage);
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
