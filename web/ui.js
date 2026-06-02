// ui.js — renders the view-model pushed from Python and wires the title-bar
// controls. State flows one way: Python → window.onState(vm). Controls call
// back into Python via window.pywebview.api.*.

'use strict';

const $ = (id) => document.getElementById(id);
const BOARD_SLOTS = 8;

let settings = { damageMode: 'matchup', rollMode: 'average', onTop: true };
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
  $('damage-mode-note').textContent = `(${settings.damageMode})`;
  const pillEl = $('result-pill');
  if (!d || d.error || d.first8Turns == null) {
    // R23: damage-total element removed; only the per-turn list + pill render.
    $('damage-turns').innerHTML = d && d.error
      ? `<span class="empty-note">${d.error}</span>` : '';
    pillEl.style.display = 'none';
    applyBoardHighlight($('me-board'), null);
    return;
  }

  // Matchup: emit the WIN @Tn / LOSE @Tn / DRAW chip + highlight the slot.
  if (d.matchup && d.outcome && d.outcome !== 'undecided') {
    let label, cls;
    if (d.outcome === 'win') { label = `WIN @T${d.endTurn ?? '?'}`; cls = 'win'; }
    else if (d.outcome === 'lose') { label = `LOSE @T${d.endTurn ?? '?'}`; cls = 'lose'; }
    else { label = `DRAW`; cls = 'draw'; }
    pillEl.className = 'result-pill ' + cls;
    pillEl.textContent = label;
    pillEl.style.display = '';
  } else if (d.matchup) {
    pillEl.className = 'result-pill draw';
    pillEl.textContent = `UNRESOLVED`;
    pillEl.style.display = '';
  } else {
    pillEl.style.display = 'none';
  }

  // Per-turn list, capped at T8 even if the battle ran longer.
  const dealt = (d.cumulativeDamage || []).slice(0, 8);
  $('damage-turns').innerHTML = dealt.map(
    (v, i) => `<span class="turn">T${i + 1} <b>${Math.round(v)}</b></span>`
  ).join('');

  // Highlight the slot the player last played (green if won, red if lost).
  applyBoardHighlight($('me-board'), d.matchup ? d : null);
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
async function updateDamage(vm) {
  if (!window.yisim || !vm || !vm.me) return;
  const me = vm.me;
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
    mode: settings.damageMode,
  };
  if (settings.damageMode === 'matchup' && vm.opponent && vm.opponent.board) {
    const opp = vm.opponent;
    const oppDeckSlots = opp.unlocked || deckSlots;
    opts.opponentSlots = (opp.board || []).slice(0, oppDeckSlots).map(
      (c) => (c ? slotFromCard(c) : null)
    );
    opts.opponentState = {
      hp: opp.hp, maxHp: opp.hp,
      physique: opp.tipo || 0, maxPhysique: opp.tipo || 0,
      cultivation: opp.xiuwei || 0,
    };
    // R26: opponent fates now flow through yisim too. proxy_view emits
    // `opp.fates` in the same talent-object shape as `me.fates`, so the
    // simulator's normalizeTalents accepts it directly.
    opts.opponentTalents = (opp.fates || []);
  }
  const token = ++_simToken;
  try {
    const result = await window.yisim.simulate(slots, opts);
    if (token === _simToken) renderDamageResult(result);
  } catch (e) {
    if (token === _simToken) renderDamageResult({ error: String(e) });
  }
}

function renderDamage(vm) {
  $('damage-mode-note').textContent = `(${settings.damageMode})`;
  updateDamage(vm);
}

function render(vm) {
  if (!vm) return;
  $('round-label').textContent = `Round ${vm.round ?? '—'}`;
  $('phase-label').textContent = vm.phase || '';

  const me = vm.me || {};
  // HP prefix uses '~' when predicted (formula fallback, BattleLog.json not
  // available for this round) and nothing when authoritative (from BL).
  const meHpStr = me.hp == null ? '—' : (me.hpIsPredicted ? `~${me.hp}` : `${me.hp}`);
  $('me-stats').textContent = me.destiny != null
    ? `命${me.destiny} · HP${meHpStr} · 修${me.xiuwei ?? 0} · 体${me.tipo ?? 0} · 境${me.realm_tier ?? 1} · 转${me.rerolls ?? '—'}`
    : '';
  renderFates($('me-fates'), me.fateNames, me.fates);
  renderBoard($('me-board'), me.board, me.unlocked);
  renderHand($('hand-list'), me.hand, me.seasonal);

  const opp = vm.opponent || {};
  // Round 14: opp.board is now the current-round board (was previous-round).
  const boardSrc = opp.boardFromRound ? `current board R${opp.boardFromRound}` : 'no board yet';
  const oppHpStr = opp.hp == null ? '—' : (opp.hpIsPredicted ? `~${opp.hp}` : `${opp.hp}`);
  $('opp-stats').textContent = opp.destiny != null
    ? `命${opp.destiny} · HP${oppHpStr} · 修${opp.xiuwei ?? 0} · 体${opp.tipo ?? 0} · 境${opp.realm_tier ?? 1} · ${opp.phase || vm.phase || ''} · ${boardSrc}`
    : '';
  renderOppFates($('opp-fates'), opp.fateNames, opp.fates);
  renderBoard($('opp-board'), opp.board, opp.unlocked);

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
const FIXED_WIDTH = 360;
let lastResizeH = -1;
let resizePending = false;

function fitWindowToContent() {
  if (resizePending) return;
  resizePending = true;
  requestAnimationFrame(async () => {
    resizePending = false;
    // body.scrollHeight = titlebar + main content (including margins/padding).
    // Min 40 keeps us above the titlebar collapse height (34) so a single
    // bad measurement can't fully hide the window. Max 900 prevents a
    // pathological vm from spawning a screen-tall window.
    const h = Math.max(40, Math.min(900, Math.ceil(document.body.scrollHeight)));
    if (h === lastResizeH) return;
    lastResizeH = h;
    const a = window.pywebview && window.pywebview.api;
    if (a) {
      try { await a.resize_main(FIXED_WIDTH, h); } catch (_) {}
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

function applyModeButton() {
  $('btn-mode').textContent = settings.damageMode;
}

window.addEventListener('pywebviewready', async () => {
  const a = await api();
  if (a) {
    try { settings = await a.get_settings(); } catch (_) {}
  }
  applyModeButton();
});

$('btn-mode').addEventListener('click', async () => {
  settings.damageMode = settings.damageMode === 'matchup' ? 'solo' : 'matchup';
  applyModeButton();
  const a = await api();
  if (a) a.set_setting('damageMode', settings.damageMode);
  if (lastVM) renderDamage(lastVM); // M5: re-simulate; for now just relabel
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
