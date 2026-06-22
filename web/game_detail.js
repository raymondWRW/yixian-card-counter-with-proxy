// game_detail.js — per-round detail view: ME and OPPONENT boards, fates,
// and the winner. Asks Python which game to render via get_detail_game_id.
const $ = (id) => document.getElementById(id);

// ── Fate icon mapping ────────────────────────────────────────────────────────
// Fate icon filenames in assets/fates/ look like Icon_Talent_<id>.png. The
// runtimeKey is stable per fate; the fate object also has a `position` /
// `phase`. The wiki uses different IDs in its icon filenames, so we can't
// derive them from the fate's runtime ID directly — fall back to a generic
// icon when the specific filename isn't predictable.
function fateIcon(fate) {
  // Wiki ID heuristic: if runtimeKey carries a numeric suffix, try that.
  // (Not always present; UI falls back to no-icon gracefully.)
  return null;
}

function cardChip(c) {
  if (!c || !c.name) return '<span class="card-chip">·</span>';
  const dreamCls = c.name.startsWith('梦') ? ' dream' : '';
  const lv = (c.level || 1) > 1 ? `<span class="lv">${c.level}</span>` : '';
  return `<span class="card-chip${dreamCls}">${c.name}${lv}</span>`;
}

function fateChip(name) {
  return `<span class="fate-chip">${name}</span>`;
}

function sideHtml(side, opp) {
  const cls = opp ? 'round-side opp' : 'round-side';
  const avatar = side.character_avatar
    ? `<div class="avatar" style="background-image: url('${side.character_avatar}');"></div>`
    : `<div class="avatar placeholder"></div>`;
  const sectIcon = side.sect_icon ? `<img src="${side.sect_icon}" alt="" style="width:11px;height:11px;vertical-align:-2px">` : '';
  const lifeColor = (side.life ?? 0) <= 0 ? 'lose' : '';
  const cards = (side.board || []).map(cardChip).join('');
  const fates = (side.fate_names || []).map(fateChip).join('');
  const meta = `
    <div class="side-meta">
      <div class="name">${sectIcon} ${side.character || '?'}<span style="color:var(--muted);font-weight:400;font-size:11px;margin-left:4px">${side.username || ''}</span></div>
      <div class="stats">
        <span class="${lifeColor}"><b>${side.life ?? '?'}</b>命</span>
        <span><b>${side.xiuwei ?? 0}</b>修</span>
        <span><b>${side.tipo ?? 0}/${side.max_tipo ?? 0}</b>体</span>
        <span><b>${side.level ?? '?'}</b>境</span>
      </div>
      <div class="row-fates">${fates}</div>
      <div class="row-cards">${cards}</div>
    </div>`;
  return opp ? `<div class="${cls}">${meta}${avatar}</div>`
             : `<div class="${cls}">${avatar}${meta}</div>`;
}

function renderRounds(detail) {
  $('detail-empty').style.display = 'none';
  $('rounds-list').style.display = '';
  $('game-id').textContent = detail.id;
  $('rounds-list').innerHTML = (detail.rounds || []).map((r) => {
    const cls = r.won ? 'won' : 'lost';
    const me = r.me;
    const opp = r.opponent;
    const outcomeLabel = r.won
      ? `<span class="round-outcome won">WIN</span>`
      : `<span class="round-outcome lost">LOSE</span>`;
    const deltaStr = (r.life_delta > 0 ? '+' : '') + r.life_delta;
    return `
      <div class="round-row ${cls}">
        ${sideHtml(me, false)}
        <div class="round-vs">
          <span class="round-num">R${r.round}</span>
          ${outcomeLabel}
          <span class="round-delta">Δ${deltaStr}</span>
        </div>
        ${sideHtml(opp, true)}
      </div>`;
  }).join('');
}

$('btn-quit').addEventListener('click', async () => {
  try { await window.pywebview.api.close_detail(); } catch (_) {}
});

window.addEventListener('pywebviewready', async () => {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;
  let id;
  try { id = await api.get_detail_game_id(); } catch (_) { id = null; }
  if (!id) {
    $('detail-empty').textContent = '没有选择对局';
    return;
  }
  try {
    const d = await api.game_detail(id);
    if (d && d.error) {
      $('detail-empty').textContent = '加载失败: ' + d.error;
      return;
    }
    if (!d || !d.rounds || !d.rounds.length) {
      $('detail-empty').textContent = '这局没有可显示的回合数据';
      return;
    }
    renderRounds(d);
  } catch (e) {
    $('detail-empty').textContent = '加载失败';
    console.error(e);
  }
  // Apply scale + wire drag/resize like the review window.
  try {
    const s = await api.get_settings();
    applyScale(Number(s.detailScale) || 1.0);
  } catch (_) {}
});

// ── Titlebar drag (same pattern as review.js) ────────────────────────────────
(function setupTitleDrag() {
  const bar = document.getElementById('titlebar');
  if (!bar) return;
  let dragging = false, sx = 0, sy = 0, ox = 0, oy = 0;
  bar.addEventListener('mousedown', (e) => {
    if (e.target.closest('button')) return;
    if (e.button !== 0) return;
    dragging = true;
    sx = e.screenX; sy = e.screenY;
    ox = window.screenX; oy = window.screenY;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.move_detail) {
      try { a.move_detail(ox + e.screenX - sx, oy + e.screenY - sy); } catch (_) {}
    }
  });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Bottom-right resize handle ───────────────────────────────────────────────
let detailScale = 1.0;
function applyScale(s) {
  const MIN = 0.6, MAX = 2.5;
  s = Math.max(MIN, Math.min(MAX, s));
  detailScale = s;
  document.body.style.zoom = String(s);
  const a = window.pywebview && window.pywebview.api;
  if (a && a.resize_detail) {
    try { a.resize_detail(Math.round(900 * s), Math.round(640 * s)); } catch (_) {}
  }
  return s;
}

(function setupResize() {
  const handle = document.getElementById('resize-handle');
  if (!handle) return;
  const SENS = 250;
  let dragging = false, sx = 0, sy = 0, startScale = 1;
  handle.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    sx = e.screenX; sy = e.screenY; startScale = detailScale;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.screenX - sx;
    const dy = e.screenY - sy;
    applyScale(startScale + (dx + dy) / 2 / SENS);
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      try { a.set_setting('detailScale', detailScale); } catch (_) {}
    }
  });
  window.addEventListener('blur', () => { dragging = false; });
})();
