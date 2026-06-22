// yisim_solver_fast.js — focused search with time budget + progress reports.
// Prioritizes: (1) all permutations of the original 8-card board (8!=40320),
// (2) one-swap with hand alternates, (3) two-swap, then random subsets.
// Outputs progress to stderr every 1000 sims so we can monitor and stop early.
'use strict';
const fs = require('fs');
const path = require('path');

const BUNDLE = path.join(__dirname, '..', 'web', 'yisim.bundle.js');
(0, eval)(fs.readFileSync(BUNDLE, 'utf8'));
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  const rawLevel = c.level || 1;
  return isDream
    ? { name: c.name, level: Math.min(rawLevel, 5), phase: rawLevel, isDream: true }
    : { name: c.name, level: Math.min(rawLevel, 3), isDream: false };
}

function buildPlayerState(s) {
  return { hp: s.hp, maxHp: s.hp, physique: s.tipo || 0,
    maxPhysique: s.max_tipo || s.tipo || 0, cultivation: s.xiuwei || 0 };
}

function simulate(meSlots, me, opp) {
  return Y.simulate(meSlots, {
    mode: 'matchup', rollMode: 'high',  // single deterministic sim (100x faster than 'average')
    deckSlots: meSlots.length, maxTurns: 64,
    playerState: buildPlayerState(me),
    talents: Array.isArray(me.fates) ? me.fates : [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: buildPlayerState(opp),
    opponentTalents: Array.isArray(opp.fates) ? opp.fates : [],
  });
}

function score(res) {
  if (res.outcome === 'win') return 10000 + (res.myHp || 0);
  return (res.myHp || 0) - (res.oppHp || 0);
}

function cmpSlot(a, b) {
  const ka = a ? `${a.name}@${a.level}` : '_';
  const kb = b ? `${b.name}@${b.level}` : '_';
  return ka < kb ? -1 : ka > kb ? 1 : 0;
}

function next_permutation(arr) {
  let i = arr.length - 1;
  while (i > 0 && cmpSlot(arr[i-1], arr[i]) >= 0) i -= 1;
  if (i === 0) return false;
  let j = arr.length - 1;
  while (cmpSlot(arr[j], arr[i-1]) <= 0) j -= 1;
  [arr[i-1], arr[j]] = [arr[j], arr[i-1]];
  j = arr.length - 1;
  while (i < j) { [arr[i], arr[j]] = [arr[j], arr[i]]; i++; j--; }
  return true;
}

function pkey(slots) { return slots.map(s => s ? `${s.name}@${s.level}` : '_').join('|'); }
function shuffleInPlace(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
}

(async () => {
  let buf = '';
  process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const round = j.round;
  const me = round.me, opp = round.opponent;
  if (Y.ready) { try { await Promise.resolve(Y.ready); } catch (e) {} }

  const origSlots = (me.slots || []).map(toSlot).filter(Boolean);
  const hand = Array.isArray(me.hand) ? me.hand.map(toSlot).filter(Boolean) : [];
  const pool = origSlots.concat(hand);
  const timeBudgetMs = (j.budget_seconds || 60) * 1000;
  const startTime = Date.now();

  const origRes = await Promise.resolve(simulate(origSlots, me, opp));
  let bestScore = score(origRes);
  let bestSlots = origSlots.slice();
  let bestRes = origRes;
  let tried = 1;
  const seen = new Set([pkey(origSlots)]);
  let firstWin = null;

  async function tryArr(arr, label) {
    if (Date.now() - startTime > timeBudgetMs) return 'timeout';
    const k = pkey(arr);
    if (seen.has(k)) return 'dup';
    seen.add(k);
    tried++;
    const r = await Promise.resolve(simulate(arr, me, opp));
    const s = score(r);
    if (r.outcome === 'win' && !firstWin) {
      firstWin = { slots: arr.slice(), res: r, score: s, label };
      bestScore = s; bestSlots = arr.slice(); bestRes = r;
      return 'win';
    }
    if (s > bestScore) {
      bestScore = s; bestSlots = arr.slice(); bestRes = r;
    }
    if (tried % 500 === 0) {
      process.stderr.write(`tried=${tried} best_score=${bestScore} (${bestRes.outcome} hp=${bestRes.myHp}/${bestRes.oppHp})\n`);
    }
    return 'ok';
  }

  // Phase 1: exhaustive permutations of original board
  const sorted = origSlots.slice().sort(cmpSlot);
  const perm = sorted.slice();
  process.stderr.write(`Phase 1: enumerating perms of original board...\n`);
  do {
    const r = await tryArr(perm, 'perm-orig');
    if (r === 'win' || r === 'timeout') break;
  } while (next_permutation(perm));
  if (firstWin) { reportResult(); return; }

  // Phase 2: single-card swap with each hand alternate, then perms
  process.stderr.write(`Phase 2: single hand-swap permutations... (tried=${tried})\n`);
  outer2: for (let i = 0; i < origSlots.length; i++) {
    for (const hc of hand) {
      const swapped = origSlots.slice();
      swapped[i] = hc;
      const sw = swapped.slice().sort(cmpSlot);
      do {
        const r = await tryArr(sw, `swap-${i}-${hc.name}`);
        if (r === 'win') break outer2;
        if (r === 'timeout') break outer2;
        if (tried % 2000 === 0) break; // limit perms per swap variation
      } while (next_permutation(sw));
    }
  }
  if (firstWin) { reportResult(); return; }

  // Phase 3: random subsets of full pool
  process.stderr.write(`Phase 3: random pool subsets... (tried=${tried})\n`);
  while (Date.now() - startTime < timeBudgetMs) {
    const shuf = pool.slice();
    shuffleInPlace(shuf);
    const subset = shuf.slice(0, 8);
    const r = await tryArr(subset, 'pool-rand');
    if (r === 'win') break;
  }

  reportResult();

  function reportResult() {
    process.stderr.write(`DONE tried=${tried} elapsed=${((Date.now()-startTime)/1000).toFixed(1)}s\n`);
    process.stdout.write(JSON.stringify({
      found_win: !!firstWin,
      tried,
      elapsed_seconds: (Date.now() - startTime) / 1000,
      original: { outcome: origRes.outcome, myHp: origRes.myHp, oppHp: origRes.oppHp, endTurn: origRes.endTurn },
      best: { outcome: bestRes.outcome, myHp: bestRes.myHp, oppHp: bestRes.oppHp, endTurn: bestRes.endTurn,
              slots: bestSlots, score: bestScore },
      win: firstWin,
      pool_size: pool.length,
    }, null, 2));
  }
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message), stack: e && e.stack })));
