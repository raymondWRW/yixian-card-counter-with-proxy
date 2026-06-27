// review.js — review window logic.
//
// Stage 1: list all games discovered by proxy.game_archive, with placeholder
// [Review] buttons (the per-round yisim search is Stage 2). Stats button
// opens a filter modal with placeholder content (charts also in Stage 2).
const $ = (id) => document.getElementById(id);
let games = [];

function fmtTs(id) {
  // Folder games: 2026-06-04_154414 → 06-04 15:44
  const m = id.match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (m) return `${m[2]}-${m[3]} ${m[4]}:${m[5]}`;
  // Per-round: HHMMSS → HH:MM
  const r = id.match(/^(\d{2})(\d{2})(\d{2})$/);
  if (r) return `(每轮) ${r[1]}:${r[2]}`;
  return id;
}

function fmtResult(g) {
  if (!g.rounds_played) return '<span class="col-result lost">无数据</span>';
  const lost = g.lost_rounds.length;
  const won  = g.rounds_played - lost;
  return `<span class="col-result">${won}胜</span>·<span class="col-result lost">${lost}负</span>`;
}

function renderGameList() {
  const grid = $('game-grid');
  const empty = $('game-list-empty');
  if (!games.length) {
    empty.textContent = '没有可复盘的对局';
    grid.style.display = 'none';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';
  grid.style.display = '';
  const img = (src, cls, alt) =>
    src ? `<img class="${cls}" src="${src}" alt="${alt || ''}">` : '';
  grid.innerHTML = games.map((g) => {
    const won = g.rounds_played - g.lost_rounds.length;
    const lost = g.lost_rounds.length;
    const accentStyle = g.sect_accent
      ? `--accent-row: ${g.sect_accent};` : '';
    const portraitStyle = g.character_avatar
      ? `background-image: url('${g.character_avatar}');` : '';
    // 查看 (per-round card view) and 复盘 (winnable re-sim) both work for every
    // game now — recorded games use battle_log, imported games decode the
    // recentBattleDatas record (exact board + levels + stats).
    const reviewBtn = g.lost_rounds.length === 0
      ? `<button class="btn-review" disabled>全胜</button>`
      : `<button class="btn-review" data-id="${g.id}">复盘 ${g.lost_rounds.length}</button>`;
    const viewBtn = `<button class="btn-view" data-id="${g.id}">查看</button>`;
    return `
      <div class="game-card" style="${accentStyle}">
        <div class="game-portrait${g.character_avatar ? '' : ' no-portrait'}"
             style="${portraitStyle}"></div>
        <div class="game-meta">
          <div class="row-1">
            <span class="name">${g.character || '?'}</span>
            <span class="ts">${fmtTs(g.id)}</span>
          </div>
          <div class="row-2">
            ${img(g.sect_icon, '', g.sect)}<span class="sect-name">${g.sect || '?'}</span>
            <span style="opacity:.4">·</span>
            ${img(g.sidejob_badge, '', g.sidejob)}<span class="side-name">${g.sidejob || '?'}</span>
          </div>
          <div class="row-3">
            ${g.placement ? `<span class="pip placement p${g.placement}"><b>#${g.placement}</b></span>` : ''}
            <span class="pip"><b>${g.rounds_played}</b>回合</span>
            <span class="pip win"><b>${won}</b>胜</span>
            <span class="pip lose"><b>${lost}</b>负</span>
          </div>
        </div>
        <div class="game-action">${viewBtn}${reviewBtn}</div>
      </div>`;
  }).join('');

  for (const btn of grid.querySelectorAll('.btn-review[data-id]')) {
    btn.addEventListener('click', () => onReview(btn.dataset.id, btn));
  }
  for (const btn of grid.querySelectorAll('.btn-view[data-id]')) {
    btn.addEventListener('click', async () => {
      try { await window.pywebview.api.open_game_detail(btn.dataset.id); }
      catch (e) { console.error(e); }
    });
  }
}

// Cache of per-game review results so the 解法 buttons can look up the
// winning slots after the review completes (keyed by game id → round).
const _reviewCache = {};   // gameId → { roundN → details {win, winning_slots, end_turn} }

async function onReview(gameId, btn) {
  btn.textContent = '计算中…';
  btn.disabled = true;
  try {
    const api = window.pywebview && window.pywebview.api;
    if (!api || !api.review_game) {
      btn.textContent = '尚未实现';
      btn.classList.add('none-found');
      return;
    }
    const result = await api.review_game(gameId);
    if (result && result.skipped) {
      btn.textContent = '此场无法复盘';
      btn.classList.add('none-found');
      btn.title = result.error || '只支持新格式 (per-round) 对局';
      return;
    }
    if (!result || result.error) {
      btn.textContent = '复盘失败';
      btn.classList.add('none-found');
      btn.title = (result && result.error) || 'unknown';
      return;
    }
    // Cache per-round details for the 解法 buttons.
    _reviewCache[gameId] = {};
    for (const d of (result.details || [])) {
      _reviewCache[gameId][d.round] = d;
    }
    const won = result.winnable_rounds || [];
    if (!won.length) {
      btn.textContent = `无解 (${result.lost_rounds.length}负)`;
      btn.classList.add('none-found');
      btn.title = '尝试了 300 种摆法,没找到能赢的';
      return;
    }
    btn.textContent = `可赢 R${won.join(', R')}`;
    btn.classList.add('reviewed');
    btn.title = `${won.length}/${result.lost_rounds.length} 个负场存在可赢摆法`;
    // Append 解法 buttons inside the same game-action column.
    const actionCell = btn.parentElement;
    if (actionCell) {
      // Drop any stale 解法 buttons from a previous click.
      for (const old of actionCell.querySelectorAll('.btn-solution')) old.remove();
      for (const rn of won) {
        const sBtn = document.createElement('button');
        sBtn.className = 'btn-solution';
        // ⚡ flags a go-first line (wins only if the player takes the first turn).
        const gf = (_reviewCache[gameId][rn] || {}).requires_go_first ? ' ⚡' : '';
        sBtn.textContent = `解法 R${rn}${gf}`;
        sBtn.dataset.gameId = gameId;
        sBtn.dataset.round = String(rn);
        sBtn.addEventListener('click', () => showSolution(gameId, rn));
        actionCell.appendChild(sBtn);
      }
    }
  } catch (e) {
    btn.textContent = '复盘失败';
    btn.classList.add('none-found');
    console.error(e);
  } finally {
    btn.disabled = false;
  }
}

// ─── 解法 (Solution) popover ────────────────────────────────────────────────
// Shows the 8-slot winning arrangement found by yisim_review.js.
function showSolution(gameId, rn) {
  const details = (_reviewCache[gameId] || {})[rn];
  if (!details || !details.win || !details.winning_slots) return;
  const slots = details.winning_slots;
  const endTurn = details.end_turn ? `@T${details.end_turn}` : '';
  const slotHtml = slots.map((c, i) => {
    if (!c) return `<div class="sol-slot empty"><span class="pos">${i + 1}</span>普攻</div>`;
    const lv = (c.level || 1) > 1 ? `<span class="lv">lv${c.level}</span>` : '';
    const dreamCls = (c.name || '').startsWith('梦') ? ' dream' : '';
    return `<div class="sol-slot${dreamCls}"><span class="pos">${i + 1}</span><span class="cname">${c.name}</span>${lv}</div>`;
  }).join('');
  $('sol-title').textContent = `R${rn} 解法 ${endTurn}`;
  // Go-first line: this board only wins if the player takes the first turn. Surface it prominently
  // with the achievability hint (absorb cards for cultivation; hand_cards = cards held that round).
  const goFirst = details.requires_go_first
    ? `<div class="sol-note">⚡ 需先手取胜：吸收手牌提升修为以抢先手（当前手牌 ${details.hand_cards} 张）</div>`
    : '';
  $('sol-body').innerHTML = `${goFirst}<div class="sol-grid">${slotHtml}</div>`;
  $('sol-modal').style.display = '';
}

$('sol-close').addEventListener('click', () => {
  $('sol-modal').style.display = 'none';
});
$('sol-modal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) $('sol-modal').style.display = 'none';
});

// ─── Stats modal ────────────────────────────────────────────────────────────
function populateFilters() {
  const chars = new Set(), sides = new Set();
  for (const g of games) {
    if (g.character && g.character !== '?') chars.add(g.character);
    if (g.sidejob && g.sidejob !== '?') sides.add(g.sidejob);
  }
  const fc = $('filter-character'); const fs = $('filter-sidejob');
  fc.innerHTML = '<option value="">全部</option>' +
    [...chars].sort().map((c) => `<option>${c}</option>`).join('');
  fs.innerHTML = '<option value="">全部</option>' +
    [...sides].sort().map((s) => `<option>${s}</option>`).join('');
}

function applyStatsFilter() {
  const fc = $('filter-character').value;
  const fs = $('filter-sidejob').value;
  const fr = Number($('filter-recent').value) || 0;
  let pool = games.slice();
  if (fc) pool = pool.filter((g) => g.character === fc);
  if (fs) pool = pool.filter((g) => g.sidejob === fs);
  if (fr) pool = pool.slice(0, fr);

  // ── Placement metrics (the headline) ──────────────────────────────────────
  // Only games with a known final placement (1..8) count here. Per-round-format
  // games and any unresolved game have placement == null and are excluded from
  // the placement stats (but still counted in the round-level summary below).
  const placed = pool.filter((g) => g.placement >= 1 && g.placement <= 8);
  const n = placed.length;
  const sum = placed.reduce((s, g) => s + g.placement, 0);
  const avg = n ? sum / n : null;
  const firsts = placed.filter((g) => g.placement === 1).length;
  const top4 = placed.filter((g) => g.placement <= 4).length;
  const hist = [0, 0, 0, 0, 0, 0, 0, 0]; // hist[i] = count of (i+1)-th place
  for (const g of placed) hist[g.placement - 1]++;

  const pct = (k) => (n ? (100 * k / n).toFixed(0) : '—');
  const card = (label, value, sub) =>
    `<div class="stat-card"><div class="sc-value">${value}</div>` +
    `<div class="sc-label">${label}</div>` +
    (sub ? `<div class="sc-sub">${sub}</div>` : '') + `</div>`;
  $('stats-cards').innerHTML = n
    ? card('平均名次', avg.toFixed(2), `${n} 场`) +
      card('吃鸡率', `${pct(firsts)}%`, `${firsts} 场 #1`) +
      card('前四率', `${pct(top4)}%`, `${top4} 场前四`)
    : '<div class="stat-empty">这些对局没有名次数据</div>';

  // ── Placement histogram (#1..#8) ─────────────────────────────────────────
  const maxBar = Math.max(1, ...hist);
  $('placement-hist').innerHTML = hist.map((c, i) => {
    const place = i + 1;
    const h = Math.round(100 * c / maxBar);
    return `<div class="ph-col">
        <span class="ph-count">${c || ''}</span>
        <div class="ph-bar-wrap">
          <div class="ph-bar p${place}" style="height:${h}%"></div>
        </div>
        <span class="ph-place">#${place}</span>
      </div>`;
  }).join('');

  // ── Combat-strength radar ────────────────────────────────────────────────
  renderRadar(pool);

  // ── Round-level summary (kept as a secondary line) ───────────────────────
  const totalGames = pool.length;
  const totalRounds = pool.reduce((s, g) => s + g.rounds_played, 0);
  const totalLost = pool.reduce((s, g) => s + g.lost_rounds.length, 0);
  const winRate = totalRounds ? (100 * (totalRounds - totalLost) / totalRounds).toFixed(1) : '—';
  $('stats-summary').innerHTML = `
    <b>${totalGames}</b>场 · 共<b>${totalRounds}</b>回合 ·
    回合胜率 <b>${winRate}%</b> (${totalRounds - totalLost}胜 / ${totalLost}负)`;
}

// Spider/radar of combat strength across 5 categories. Strength = net destiny
// (命元 dealt − received) per round, recency-weighted (more recent games count
// a bit more) and signed-log-scaled so the shape doesn't blow out. The net=0
// (neutral) ring is dashed; outside it = you came out ahead, inside = behind.
function renderRadar(pool) {
  const el = $('radar-chart');
  if (!el) return;
  const cats = [['early', '前期'], ['mid', '中期'], ['late', '后期'],
                ['first', '先手'], ['second', '后手']];
  const N = pool.length;
  // Recency weight: newest (index 0) = 1, oldest ≈ 0.5 — a gentle bias.
  const data = cats.map(([k, lbl]) => {
    let ws = 0, wn = 0;
    pool.forEach((g, i) => {
      const r = g.radar && g.radar[k];
      if (!r) return;
      const w = Math.pow(0.5, i / Math.max(1, N - 1));
      ws += w * r.s; wn += w * r.n;
    });
    const avg = wn ? ws / wn : 0;               // weighted net destiny / round
    const val = (avg >= 0 ? 1 : -1) * Math.log(1 + Math.abs(avg));  // signed log
    return { lbl, avg, val };
  });
  // Symmetric scale so net=0 lands at the mid ring; ≥1 keeps a sane floor.
  const M = Math.max(1, ...data.map((d) => Math.abs(d.val)));
  const cx = 100, cy = 100, R = 60;
  const pt = (i, frac) => {
    const a = (-90 + i * 72) * Math.PI / 180;
    return [cx + R * frac * Math.cos(a), cy + R * frac * Math.sin(a)];
  };
  const ring = (frac) => data.map((_, i) => pt(i, frac).join(',')).join(' ');
  const dataPts = data.map((d, i) => pt(i, (d.val + M) / (2 * M)).join(',')).join(' ');
  el.innerHTML = `
    <svg viewBox="0 0 200 205" class="radar-svg">
      <polygon points="${ring(1)}" class="radar-grid"/>
      <polygon points="${ring(0.75)}" class="radar-grid"/>
      <polygon points="${ring(0.5)}" class="radar-neutral"/>
      <polygon points="${ring(0.25)}" class="radar-grid"/>
      ${data.map((_, i) => { const [x, y] = pt(i, 1);
        return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" class="radar-axis"/>`;
      }).join('')}
      <polygon points="${dataPts}" class="radar-area"/>
      ${data.map((d, i) => { const [x, y] = pt(i, (d.val + M) / (2 * M));
        return `<circle cx="${x}" cy="${y}" r="2.4" class="radar-dot"/>`;
      }).join('')}
      ${data.map((d, i) => { const [x, y] = pt(i, 1.3);
        return `<text x="${x}" y="${y}" class="radar-label">${d.lbl}</text>` +
          `<text x="${x}" y="${y + 9}" class="radar-val ${d.avg >= 0 ? 'pos' : 'neg'}">` +
          `${d.avg >= 0 ? '+' : ''}${d.avg.toFixed(1)}</text>`;
      }).join('')}
    </svg>`;
}

$('btn-stats').addEventListener('click', () => {
  populateFilters();
  applyStatsFilter();
  $('stats-modal').style.display = '';
});
$('stats-close').addEventListener('click', () => {
  $('stats-modal').style.display = 'none';
});
$('stats-modal').addEventListener('click', (e) => {
  if (e.target === e.currentTarget) $('stats-modal').style.display = 'none';
});
for (const id of ['filter-character', 'filter-sidejob', 'filter-recent']) {
  $(id).addEventListener('change', applyStatsFilter);
}

$('btn-quit').addEventListener('click', async () => {
  try { await window.pywebview.api.close_review(); } catch (_) {}
});

// Reload the games list — called on first ready AND every time the window is reopened
// (Api.open_review evaluates window.reloadGames()), so newly-played games show up.
window.reloadGames = async function () {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;
  try {
    games = await api.list_games();
  } catch (e) {
    games = [];
    console.error(e);
  }
  renderGameList();
};

window.addEventListener('pywebviewready', async () => {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;
  await window.reloadGames();
  // Apply persisted scale (same setting key as the main window).
  try {
    const s = await api.get_settings();
    applyScale(Number(s.reviewScale) || 1.0);
  } catch (_) {}
});

// ── Titlebar drag — frameless windows need a manual mousedown→move pipe ───
// pywebview's `-webkit-app-region: drag` works on the main window via
// easy_drag=True; for the review window we keep easy_drag=False so the resize
// handle stays click-targetable. So we do drag explicitly via the Python API.
(function setupTitleDrag() {
  const bar = document.getElementById('titlebar');
  if (!bar) return;
  let dragging = false, startX = 0, startY = 0, originX = 0, originY = 0;
  bar.addEventListener('mousedown', (e) => {
    // Ignore clicks on titlebar buttons.
    if (e.target.closest('button')) return;
    if (e.button !== 0) return;
    dragging = true;
    startX = e.screenX; startY = e.screenY;
    originX = window.screenX; originY = window.screenY;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.move_review) {
      try { a.move_review(originX + dx, originY + dy); } catch (_) {}
    }
  });
  window.addEventListener('mouseup', () => { dragging = false; });
  window.addEventListener('blur', () => { dragging = false; });
})();

// ── Bottom-right resize handle — scale via CSS zoom + resize the OS window ──
let reviewScale = 1.0;

function applyScale(s) {
  const MIN = 0.6, MAX = 2.5;
  s = Math.max(MIN, Math.min(MAX, s));
  reviewScale = s;
  document.body.style.zoom = String(s);
  // Resize the OS window to follow the zoomed content size.
  const a = window.pywebview && window.pywebview.api;
  if (a && a.resize_review) {
    try { a.resize_review(Math.round(720 * s), Math.round(520 * s)); } catch (_) {}
  }
  return s;
}

(function setupResize() {
  const handle = document.getElementById('resize-handle');
  if (!handle) return;
  const SENS = 250;
  let dragging = false, startX = 0, startY = 0, startScale = 1;
  handle.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    dragging = true;
    startX = e.screenX; startY = e.screenY;
    startScale = reviewScale;
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!dragging) return;
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    const delta = (dx + dy) / 2 / SENS;
    applyScale(startScale + delta);
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    const a = window.pywebview && window.pywebview.api;
    if (a && a.set_setting) {
      try { a.set_setting('reviewScale', reviewScale); } catch (_) {}
    }
  });
  window.addEventListener('blur', () => { dragging = false; });
})();
