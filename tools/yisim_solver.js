// yisim_solver.js — port of yisim's find_winning_deck.js solver, adapted to
// run single-threaded against the bundled engine. Enumerates k=8 combinations
// from a pool, then exhaustive permutations of each combo (yisim's
// next_permutation), like worker.js does. Pool can be expanded with merged
// variants of same-name+same-level pairs.
//
// stdin: { round, max_combos?: int, max_perms_per_combo?: int }
// stdout: { tried, wins, best, total_combos }
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
  return {
    hp: s.hp, maxHp: s.hp,
    physique: s.tipo || 0, maxPhysique: s.max_tipo || s.tipo || 0,
    cultivation: s.xiuwei || 0,
  };
}

function simulate(meSlots, me, opp) {
  return Y.simulate(meSlots, {
    mode: 'matchup', rollMode: 'low',  // 'low' = deterministic, single sim
    deckSlots: meSlots.length,
    maxTurns: 64,
    playerState: buildPlayerState(me),
    talents: Array.isArray(me.fates) ? me.fates : [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: buildPlayerState(opp),
    opponentTalents: Array.isArray(opp.fates) ? opp.fates : [],
  });
}

// yisim's next_permutation: in-place next lex permutation; returns false when
// the array is at the highest perm (sorted descending).
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

function cmpSlot(a, b) {
  const ka = a ? `${a.name}@${a.level}` : '_';
  const kb = b ? `${b.name}@${b.level}` : '_';
  return ka < kb ? -1 : ka > kb ? 1 : 0;
}

// All k-combinations of arr (generator)
function* k_combinations(arr, k) {
  if (k === 0) { yield []; return; }
  if (arr.length < k) return;
  const head = arr[0]; const tail = arr.slice(1);
  for (const sub of k_combinations(tail, k - 1)) yield [head, ...sub];
  for (const sub of k_combinations(tail, k)) yield sub;
}

// Expand pool with merged variants: if pool has 2+ copies of same-name+lv,
// add a level-up variant (capped at 3 since sim levels max at 3).
function expandWithMerges(pool) {
  const counts = {};
  for (const c of pool) {
    if (!c) continue;
    const k = `${c.name}@${c.level}`;
    counts[k] = (counts[k] || 0) + 1;
  }
  const merged = [];
  for (const [k, n] of Object.entries(counts)) {
    if (n >= 2) {
      const [name, lvStr] = k.split('@');
      const lv = parseInt(lvStr, 10);
      const nextLv = Math.min(lv + 1, 3);
      if (nextLv > lv) merged.push({ name, level: nextLv, isDream: name.startsWith('梦') });
    }
  }
  // Pool can include both originals AND merged options; the solver picks.
  return pool.concat(merged);
}

function score(res) {
  if (res.outcome === 'win') return 10000 + (res.myHp || 0);
  return (res.myHp || 0) - (res.oppHp || 0);
}

function keyOfCombo(combo) {
  return combo.map(c => c ? `${c.name}@${c.level}` : '_').sort().join('|');
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
  let pool = origSlots.concat(hand);
  pool = expandWithMerges(pool);

  const maxCombos = j.max_combos || 20000;
  const maxPermsPerCombo = j.max_perms_per_combo || 200;
  const deckSlots = 8;

  // Count total possible combos for reporting
  let totalCombos = 1;
  {
    const n = pool.length, k = deckSlots;
    if (k > n) totalCombos = 0;
    else {
      let c = 1;
      for (let i = 1; i <= k; i++) c = c * (n - i + 1) / i;
      totalCombos = Math.floor(c);
    }
  }

  // Score original first
  const origSim = await Promise.resolve(simulate(origSlots, me, opp));
  let bestScore = score(origSim);
  let bestSlots = origSlots.slice();
  let bestRes = origSim;
  let wins = 0;
  let totalTried = 1;
  let combosTried = 0;

  const seenCombos = new Set();
  const seenPerms = new Set();
  seenPerms.add(cmpSlot.length ? origSlots.map(s => `${s.name}@${s.level}`).join('|') : '');

  for (const combo of k_combinations(pool, deckSlots)) {
    if (combosTried >= maxCombos) break;
    const ckey = keyOfCombo(combo);
    if (seenCombos.has(ckey)) continue;
    seenCombos.add(ckey);
    combosTried++;

    // Filter: combos with too many continuous/consumption-like cards
    // (heuristic skip — keeps search efficient)
    const continuousLike = combo.filter(c => {
      const n = c.name;
      return n.includes('心法') || n.includes('剑阵') || n === '千里神行符';
    }).length;
    if (continuousLike >= 4) continue;

    // Enumerate next_permutation starting from sorted
    const perm = combo.slice().sort(cmpSlot);
    let permTried = 0;
    do {
      if (permTried >= maxPermsPerCombo) break;
      const pkey = perm.map(s => `${s.name}@${s.level}`).join('|');
      if (seenPerms.has(pkey)) { permTried++; continue; }
      seenPerms.add(pkey);
      permTried++;
      totalTried++;
      const r = await Promise.resolve(simulate(perm, me, opp));
      const s = score(r);
      if (r.outcome === 'win') {
        wins++;
        if (s > bestScore) { bestScore = s; bestSlots = perm.slice(); bestRes = r; }
        // Stop early: report first win to keep solver responsive
        process.stdout.write(JSON.stringify({
          found_win: true,
          tried: totalTried, combos_tried: combosTried, total_combos: totalCombos,
          best: { outcome: r.outcome, myHp: r.myHp, oppHp: r.oppHp, endTurn: r.endTurn,
                  slots: perm.slice(), score: s },
        }, null, 2));
        return;
      }
      if (s > bestScore) { bestScore = s; bestSlots = perm.slice(); bestRes = r; }
    } while (next_permutation(perm));
  }

  process.stdout.write(JSON.stringify({
    found_win: false,
    tried: totalTried, combos_tried: combosTried, total_combos: totalCombos,
    wins,
    original: { outcome: origSim.outcome, myHp: origSim.myHp, oppHp: origSim.oppHp, endTurn: origSim.endTurn },
    best: { outcome: bestRes.outcome, myHp: bestRes.myHp, oppHp: bestRes.oppHp, endTurn: bestRes.endTurn,
            slots: bestSlots, score: bestScore },
    pool_size: pool.length,
  }, null, 2));
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message), stack: e && e.stack })));
