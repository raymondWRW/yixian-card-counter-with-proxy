// ui.js — renders the view-model pushed from Python and wires the title-bar
// controls. State flows one way: Python → window.onState(vm). Controls call
// back into Python via window.pywebview.api.*.

'use strict';

const $ = (id) => document.getElementById(id);
const BOARD_SLOTS = 8;

// damageMode is locked to 'solo' — matchup mode and the toggle button have
// been removed from the UI. Keep the field for downstream callers that read it.
let settings = { damageMode: 'solo', rollMode: 'average', onTop: true };
let lastVM = null;
let lastStateAt = 0;

// ── Rendering ──────────────────────────────────────────────────────────────
function lvTag(level) {
  return level && level > 1 ? ` <span class="lv">lv${level}</span>` : '';
}

function renderBoard(el, board, unlocked) {
  el.innerHTML = '';
  const slots = board || [];
  for (let i = 0; i < BOARD_SLOTS; i++) {
    const card = slots[i];
    const div = document.createElement('div');
    div.className = 'slot';
    if (typeof unlocked === 'number' && i >= unlocked) {
      div.className += ' locked';
      div.textContent = '🔒';
    } else if (!card) {
      div.className += ' empty';
      div.textContent = '·';
    } else {
      div.innerHTML = `${card.name}${lvTag(card.level)}`;
    }
    el.appendChild(div);
  }
}

// Highlight the slot that played the killing/final card in the most recent
// simulated battle. Green if YOU won, red if you lost, gray if undecided. If
// the battle took longer than 8 turns, write the end-turn number in the
// bottom-right of that slot.
function applyBoardHighlight(boardEl, d) {
  if (!boardEl) return;
  for (const slot of boardEl.querySelectorAll('.slot')) {
    slot.classList.remove('played-win', 'played-lose', 'played-draw');
    const tag = slot.querySelector('.end-turn');
    if (tag) tag.remove();
  }
  if (!d || d.lastSlotMe == null) return;
  const i = Number(d.lastSlotMe);
  const slots = boardEl.querySelectorAll('.slot');
  if (!(i >= 0 && i < slots.length)) return;
  const cls = d.outcome === 'win' ? 'played-win'
            : d.outcome === 'lose' ? 'played-lose'
            : d.outcome === 'draw' ? 'played-draw'
            : null;
  if (!cls) return;
  slots[i].classList.add(cls);
  if (d.endTurn && d.endTurn > 8) {
    const tag = document.createElement('span');
    tag.className = 'end-turn';
    tag.textContent = `T${d.endTurn}`;
    slots[i].appendChild(tag);
  }
}

function renderCounter(el, remaining) {
  el.innerHTML = '';
  const entries = Object.entries(remaining || {});
  if (!entries.length) {
    el.innerHTML = '<div class="empty-note">no data yet</div>';
    return;
  }
  entries.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]));
  for (const [name, n] of entries) {
    const row = document.createElement('div');
    row.className = 'row' + (n <= 1 ? ' low' : '');
    row.innerHTML = `<span class="name">${name}</span><span class="n">${n}</span>`;
    el.appendChild(row);
  }
}

function renderFates(el, names, talents) {
  el.innerHTML = '';
  const list = names || [];
  if (!list.length) { el.style.display = 'none'; return; }
  el.style.display = 'flex';
  // Which fates the sim actually applies (others are display-only).
  const applied = new Set((talents || [])
    .filter((t) => t && t.simulationKind && t.simulationKind !== 'non-combat-or-unsupported')
    .map((t) => t.name));
  // Map English sim-name back to its display index isn't 1:1; just badge each
  // Chinese name and mark the ones that feed the sim.
  let appliedCount = applied.size;
  list.forEach((cn, i) => {
    const chip = document.createElement('span');
    const isApplied = i < (talents || []).length &&
      talents[i] && talents[i].simulationKind &&
      talents[i].simulationKind !== 'non-combat-or-unsupported';
    chip.className = 'fate' + (isApplied ? ' applied' : '');
    chip.textContent = cn;
    chip.title = isApplied ? 'affects damage sim' : 'display only (not simulated)';
    el.appendChild(chip);
  });
}

function renderHand(el, hand, seasonal) {
  el.innerHTML = '';
  const cards = (hand || []).filter(Boolean);
  const parked = (seasonal || []).filter(Boolean);
  if (!cards.length && !parked.length) {
    el.innerHTML = '<div class="empty-note">empty</div>';
    return;
  }
  for (const c of cards) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.innerHTML = `${c.name}${lvTag(c.level)}`;
    el.appendChild(chip);
  }
  // 织梦 (dream-vase) sub-row: cards parked in the seasonal holding.
  if (parked.length) {
    const sub = document.createElement('div');
    sub.className = 'hand-sub';
    const label = document.createElement('small');
    label.className = 'sub-label';
    label.textContent = '织梦';
    sub.appendChild(label);
    for (const c of parked) {
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.innerHTML = `${c.name}${lvTag(c.level)}`;
      sub.appendChild(chip);
    }
    el.appendChild(sub);
  }
}

function renderDamageResult(d) {
  $('damage-mode-note').textContent = '(solo)';
  const pillEl = $('result-pill');
  if (!d || d.error || d.first8Turns == null) {
    $('damage-turns').innerHTML = d && d.error
      ? `<span class="empty-note">${d.error}</span>` : '';
    pillEl.style.display = 'none';
    applyBoardHighlight($('me-board'), null);
    return;
  }
  // Solo-only: no WIN/LOSE pill, no board highlight (no opponent to compare to).
  pillEl.style.display = 'none';
  const dealt = (d.cumulativeDamage || []).slice(0, 8);
  $('damage-turns').innerHTML = dealt.map(
    (v, i) => `<span class="turn">T${i + 1} <b>${Math.round(v)}</b></span>`
  ).join('');
  applyBoardHighlight($('me-board'), null);
}

// Build the yisim slot/options payload from a view-model and simulate. Guarded
// by a token so only the latest request updates the panel.
let _simToken = 0;

// Map a view-model card to the slot shape yisim expects.
// `level` is set for both regular and dream cards (regular cards use it);
// `phase` is set equal to level for dream cards (yisim's resolver looks at
// `phase` to pick the right D-variant — without it dream cards all collapse
// to phase 1 and damage looks wrong).
// `isDream` tells yisim's isDreamSlot check directly (the engine also detects
// dream cards by the 梦 name prefix as a fallback).
function slotFromCard(c) {
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  return isDream
    ? { name: c.name, level: c.level, phase: c.level, isDream: true }
    : { name: c.name, level: c.level, isDream: false };
}
// Render a Yi Xian Oracle MATCHUP result (the game's own engine): WIN/LOSE pill by
// destiny (命) damage, plus 命 / board-HP / turns. d = {win, hpDelta, turns, lifeDamage}.
function renderOracleResult(d) {
  $('damage-mode-note').textContent = '(oracle · 对战)';
  const pillEl = $('result-pill');
  const sign = d.lifeDamage > 0 ? 1 : d.lifeDamage < 0 ? -1 : 0;
  pillEl.style.display = '';
  pillEl.textContent = sign > 0 ? 'WIN' : sign < 0 ? 'LOSE' : 'DRAW';
  pillEl.className = 'pill ' + (sign > 0 ? 'win' : sign < 0 ? 'lose' : 'draw');
  const f = (v) => (v > 0 ? '+' : '') + v;
  $('damage-turns').innerHTML =
    `<span class="turn">命 <b>${f(d.lifeDamage)}</b></span>` +
    `<span class="turn">HP <b>${f(d.hpDelta)}</b></span>` +
    `<span class="turn">回合 <b>${d.turns}</b></span>`;
  applyBoardHighlight($('me-board'), null);
}

async function updateDamage(vm) {
  if (!vm || !vm.me) return;
  const me = vm.me;
  // 灵羽 (Spirit Feather) on board with no eligible lv1 merge target → yisim
  // has no implementation for it, so the damage sim would silently treat it
  // as 普通攻击 (3 dmg/turn) and under-count damage. Surface this explicitly
  // instead of running the sim with bad data.
  if (Array.isArray(me.lingyuUnresolved) && me.lingyuUnresolved.length > 0) {
    renderDamageResult({ error: '未识别卡片 (灵羽) — 伤害计算不可用' });
    return;
  }

  // Prefer the Yi Xian Oracle (the game's OWN combat engine) for a real matchup
  // vs the opponent's board, when both boards + the Python API are available. It
  // handles every card/fate natively (no yisim lag). Falls back to yisim solo.
  const api = window.pywebview && window.pywebview.api;
  const mo = me.oracle, oo = vm.opponent && vm.opponent.oracle;
  if (api && api.oracle_matchup && mo && oo &&
      (mo.usedCards || []).some((x) => x) && (oo.usedCards || []).some((x) => x)) {
    const token = ++_simToken;
    try {
      const r = await api.oracle_matchup(mo, oo, false);
      if (token !== _simToken) return;
      if (r && !r.error && r.lifeDamage != null) { renderOracleResult(r); return; }
    } catch (e) { /* fall through to yisim */ }
  }
  if (!window.yisim) return;

  // Deck size = unlocked board slots (locked slots are excluded by the slice).
  // Empty UNLOCKED slots stay as nulls so yisim plays them as 普通攻击
  // (Normal Attack, 3 dmg/turn) — that matches what the real game does for
  // unfilled-but-unlocked slots.
  const deckSlots = me.unlocked || 8;
  // Dream cards (梦•X) use `phase` (1..5) instead of `level` to pick the
  // right variant inside yisim. For regular cards `level` is what yisim wants.
  // Pass BOTH so the engine resolves correctly either way.
  const slots = (me.board || []).slice(0, deckSlots).map(
    (c) => (c ? slotFromCard(c) : null)
  );
  const opts = {
    rollMode: settings.rollMode || 'average',
    deckSlots,
    maxTurns: 64,
    playerState: {
      hp: me.hp, maxHp: me.hp,
      physique: me.tipo || 0, maxPhysique: me.tipo || 0,
      cultivation: me.xiuwei || 0,
    },
    talents: (me.fates || []),
    mode: 'solo',
  };
  // Matchup mode is disabled — only solo damage is computed (your board
  // vs a generic opponent). No opponent slots / state passed to yisim.
  const token = ++_simToken;
  try {
    const result = await window.yisim.simulate(slots, opts);
    if (token === _simToken) renderDamageResult(result);
  } catch (e) {
    if (token === _simToken) renderDamageResult({ error: String(e) });
  }
}

function renderDamage(vm) {
  $('damage-mode-note').textContent = '(solo)';
  updateDamage(vm);
}

function render(vm) {
  if (!vm) return;
  updateReviewButtonVisibility(vm);
  $('round-label').textContent = `Round ${vm.round ?? '—'}`;
  $('phase-label').textContent = vm.phase || '';

  // YOU / OPPONENT / HAND sections were removed from the main window — they
  // now live exclusively in the counter window. Each $() lookup is guarded
  // because the elements may not exist in this layout.
  const me = vm.me || {};
  const opp = vm.opponent || {};
  const meHpStr = me.hp == null ? '—' : (me.hpIsPredicted ? `~${me.hp}` : `${me.hp}`);
  const meStats = $('me-stats');
  if (meStats) meStats.textContent = me.destiny != null
    ? `命${me.destiny} · HP${meHpStr} · 修${me.xiuwei ?? 0} · 体${me.tipo ?? 0} · 境${me.realm_tier ?? 1} · 转${me.rerolls ?? '—'}`
    : '';
  const meFates = $('me-fates'); if (meFates) renderFates(meFates, me.fateNames, me.fates);
  const meBoard = $('me-board'); if (meBoard) renderBoard(meBoard, me.board, me.unlocked);
  const handList = $('hand-list'); if (handList) renderHand(handList, me.hand, me.seasonal);

  const boardSrc = opp.boardFromRound ? `current board R${opp.boardFromRound}` : 'no board yet';
  const oppHpStr = opp.hp == null ? '—' : (opp.hpIsPredicted ? `~${opp.hp}` : `${opp.hp}`);
  const oppStats = $('opp-stats');
  if (oppStats) oppStats.textContent = opp.destiny != null
    ? `命${opp.destiny} · HP${oppHpStr} · 修${opp.xiuwei ?? 0} · 体${opp.tipo ?? 0} · 境${opp.realm_tier ?? 1} · ${opp.phase || vm.phase || ''} · ${boardSrc}`
    : '';
  const oppFates = $('opp-fates'); if (oppFates) renderOppFates(oppFates, opp.fateNames, opp.fates);
  const oppBoard = $('opp-board'); if (oppBoard) renderBoard(oppBoard, opp.board, opp.unlocked);

  // Counter lives in a separate window (web/counter.html). Skip rendering it
  // here if the counter-list element is absent in this layout.
  const counterEl = $('counter-list');
  if (counterEl) renderCounter(counterEl, (vm.counter || {}).remaining);
  renderDamage(vm);
  fitWindowToContent();
}

// ── Window auto-resize ─────────────────────────────────────────────────────
// After each render we ask the OS window to match the content's natural
// height (titlebar + visible cards). Width stays fixed at FIXED_WIDTH; the
// user can drag the window around but not resize it (frameless = no edge
// handles). Mirrors the lite version and the companion counter window.
// Fixed aspect ratio for the main window — the resize handle scales BOTH
// dimensions together. We don't drive height from scrollHeight here because
// the damage card's flex layout reflows (chips fit in fewer/more rows as
// width changes), creating a feedback loop where wider → shorter and vice
// versa. Aspect locked at BASE_HEIGHT / FIXED_WIDTH = 200/360 ≈ 0.56.
const FIXED_WIDTH = 360;
const BASE_HEIGHT = 200;
let lastResizeH = -1;
let resizePending = false;
let currentUiScale = 1.0;

function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    const w = Math.round(FIXED_WIDTH * currentUiScale);
    const h = Math.max(40, Math.min(1400, Math.round(BASE_HEIGHT * currentUiScale)));
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize_main(w, h); } catch (_) {}
    }
  });
}

// Opponent fate row — same chips as renderFates, but if the list is empty
// show a single "fates: unknown" placeholder chip (the protobuf doesn't
// expose other players' fate picks).
function renderOppFates(el, names, talents) {
  el.innerHTML = '';
  el.style.display = 'flex';
  if (!names || !names.length) {
    const chip = document.createElement('span');
    chip.className = 'fate unknown';
    chip.textContent = 'fates: unknown';
    chip.title = "the protobuf doesn't expose other players' chosen fates";
    el.appendChild(chip);
    return;
  }
  renderFates(el, names, talents);
}

// ── State entry point (called from Python) ───────────────────────────────────
window.onState = function (vm) {
  lastVM = vm;
  lastStateAt = Date.now();
  $('status-dot').className = 'dot live';
  try { render(vm); } catch (e) { console.error('render failed', e); }
};

// Mark the proxy connection stale if no state arrives for a while.
setInterval(() => {
  if (!lastStateAt) return;
  const age = Date.now() - lastStateAt;
  const dot = $('status-dot');
  dot.className = 'dot ' + (age > 8000 ? 'stale' : 'live');
}, 2000);

// ── Controls ─────────────────────────────────────────────────────────────────
async function api() {
  // pywebview injects window.pywebview.api asynchronously.
  return (window.pywebview && window.pywebview.api) || null;
}

window.addEventListener('pywebviewready', async () => {
  const a = await api();
  if (a) {
    try { settings = await a.get_settings(); } catch (_) {}
  }
  // Force solo regardless of what was persisted in settings.json from an
  // earlier matchup-capable build.
  settings.damageMode = 'solo';
  // After settings load, apply the persisted UI scale (set by the
  // bottom-right resize handle in a previous session).
  if (typeof window.applyUiScale === 'function') {
    window.applyUiScale(Number(settings.uiScale) || 1.0);
  }
  // No state yet → we're "waiting for a game" → show the Review button.
  updateReviewButtonVisibility(null);
});

$('btn-pin').addEventListener('click', async () => {
  settings.onTop = !settings.onTop;
  $('btn-pin').style.opacity = settings.onTop ? '1' : '0.4';
  const a = await api();
  if (a) { a.set_setting('onTop', settings.onTop); a.set_on_top(settings.onTop); }
});

$('btn-quit').addEventListener('click', async () => {
  const a = await api();
  if (a) a.quit();
});

// Review button: always visible (in a game or not). Click → open review window.
$('btn-review').addEventListener('click', async () => {
  const a = await api();
  if (a && a.open_review) {
    try { await a.open_review(); } catch (e) { console.error(e); }
  }
});

function updateReviewButtonVisibility(vm) {
  // The 复盘 button stays visible at all times, including mid-game.
  const btn = $('btn-review');
  if (btn) btn.style.display = '';
}

// ── Minimize: collapse the body to just the titlebar (Ctrl+H or − button) ───
let _collapsed = false;
async function toggleCollapse() {
  _collapsed = !_collapsed;
  document.body.classList.toggle('collapsed', _collapsed);
  const a = await api();
  if (a && a.set_collapsed) a.set_collapsed(_collapsed);
}
$('btn-min').addEventListener('click', toggleCollapse);
window.addEventListener('keydown', (e) => {
  // Ctrl+H toggles collapse. Avoid swallowing the keystroke when the user
  // intends an input combo (we have no inputs, but be polite).
  if (e.ctrlKey && !e.altKey && !e.metaKey && e.key && e.key.toLowerCase() === 'h') {
    e.preventDefault();
    toggleCollapse();
  }
});

// ── Window dragging via the title bar ────────────────────────────────────────
// WebView2 ignores -webkit-app-region, so we move the native window ourselves:
// on title-bar mousedown we record the grab offset within the window, then on
// each mousemove move the window so the cursor keeps that same offset. Moves
// are coalesced to one per animation frame to keep the JS↔Python bridge light.
(function setupDrag() {
  const bar = $('titlebar');
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
    // Ignore clicks on the control buttons.
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

// ── Bottom-right resize handle ─────────────────────────────────────────
// Apply CSS zoom to scale the entire UI proportionally, then resize the OS
// window to match. Aspect ratio is preserved automatically because zoom
// scales all dimensions uniformly. Scale is persisted via the settings API
// so it survives restarts. Clamped to [0.6, 2.5] — below 0.6 controls
// become unreadable, above 2.5 the window outgrows typical monitors.
(function setupResize() {
  const handle = $('resize-handle');
  if (!handle) return;
  const MIN_SCALE = 0.6, MAX_SCALE = 2.5;
  // Pixels-per-scale-unit: 250px of diagonal drag = +1.0 to scale.
  const SENSITIVITY = 250;

  let uiScale = 1.0;

  function applyScale(s) {
    s = Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));
    uiScale = s;
    currentUiScale = s;  // module-level so fitWindowToContent picks it up
    // Use zoom on body — Chromium/WebView2 scales layout visually.
    document.body.style.zoom = String(s);
    lastResizeH = -1;
    fitWindowToContent();
    return s;
  }

  // Exposed so the pywebview-ready handler can apply the persisted scale
  // once settings load (which happens AFTER this IIFE runs).
  window.applyUiScale = applyScale;

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
    // Use the diagonal — bottom-right drag in either axis grows the window.
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    const delta = (dx + dy) / 2 / SENSITIVITY;
    applyScale(startScale + delta);
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    // Persist the new scale so the next launch starts at the same size.
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      try { a.set_setting('uiScale', uiScale); } catch (_) {}
    }
  });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Auto-update banner ───────────────────────────────────────────────────
// Python's updater.check_for_update_async fires window.onUpdateAvailable
// when Gitee returns a manifest newer than the bundled version. The banner
// stays hidden until then. User clicks "更新" → Python downloads the new
// exe, verifies SHA256, schedules a swap-and-relaunch, exits the process.
window.onUpdateAvailable = function (info) {
  const banner = document.getElementById('update-banner');
  const verEl = document.getElementById('update-version');
  if (!banner || !info) return;
  verEl.textContent = info.version ? `v${info.version}` : '';
  banner.style.display = 'flex';
  if (typeof fitWindowToContent === 'function') fitWindowToContent();
};

(function setupUpdate() {
  const btn = document.getElementById('update-btn');
  const dismiss = document.getElementById('update-dismiss');
  const banner = document.getElementById('update-banner');
  if (!btn || !dismiss || !banner) return;

  btn.addEventListener('click', async () => {
    const a = window.pywebview && window.pywebview.api;
    if (!a || !a.start_update) return;
    btn.disabled = true;
    btn.textContent = '下载中…';
    try {
      const res = await a.start_update();
      if (res && res.ok === false) {
        btn.disabled = false;
        btn.textContent = '重试';
        const verEl = document.getElementById('update-version');
        if (verEl) verEl.textContent = `失败: ${res.error || '未知错误'}`;
      }
      // On success the process exits — no follow-up needed.
    } catch (_) {
      btn.disabled = false;
      btn.textContent = '重试';
    }
  });

  dismiss.addEventListener('click', () => {
    banner.style.display = 'none';
    if (typeof fitWindowToContent === 'function') fitWindowToContent();
  });
})();
