// yisim_explore.js — explores many arrangements and reports the BEST end-state.
// Doesn't stop at first win; logs how close yisim gets to a win.
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
    mode: 'matchup', rollMode: 'average',
    deckSlots: me.deckSlots || meSlots.length || 8,
    maxTurns: 64,
    playerState: buildPlayerState(me),
    talents: Array.isArray(me.fates) ? me.fates : [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: buildPlayerState(opp),
    opponentTalents: Array.isArray(opp.fates) ? opp.fates : [],
  });
}

function shuffleInPlace(a) {
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
}

function keyOf(slots) {
  return slots.map(s => s ? `${s.name}@${s.level || 1}` : '_').join('|');
}

function score(res) {
  // higher = better (closer to winning)
  // Win → myHp + 1000 (big bonus); else myHp - oppHp
  if (res.outcome === 'win') return 1000 + (res.myHp || 0);
  return (res.myHp || 0) - (res.oppHp || 0);
}

(async () => {
  let buf = '';
  process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const round = j.round;
  const me = round.me, opp = round.opponent;
  if (Y.ready) { try { await Promise.resolve(Y.ready); } catch (e) {} }

  const origSlots = (me.slots || []).map(toSlot);
  const hand = Array.isArray(me.hand) ? me.hand.map(toSlot).filter(Boolean) : [];
  const deckSlots = me.deckSlots || origSlots.length || 8;
  const pool = origSlots.filter(Boolean).concat(hand);
  const maxTries = j.max_tries || 2000;

  const origRes = await Promise.resolve(simulate(origSlots, me, opp));
  let bestScore = score(origRes);
  let bestSlots = origSlots;
  let bestRes = origRes;
  let wins = 0;
  const seen = new Set([keyOf(origSlots)]);
  let tried = 1;

  function pad(arr) {
    const out = arr.slice(0, deckSlots);
    while (out.length < deckSlots) out.push(null);
    return out;
  }

  // Phase A: shuffle the original board
  for (let i = 0; i < Math.min(maxTries / 2, 500); i++) {
    const perm = origSlots.slice();
    shuffleInPlace(perm);
    const k = keyOf(perm);
    if (seen.has(k)) continue;
    seen.add(k);
    tried++;
    const r = await Promise.resolve(simulate(perm, me, opp));
    const s = score(r);
    if (r.outcome === 'win') wins++;
    if (s > bestScore) { bestScore = s; bestSlots = perm; bestRes = r; }
  }

  // Phase B: random subsets of pool
  for (let i = 0; tried < maxTries; i++) {
    const shuf = pool.slice();
    shuffleInPlace(shuf);
    const subset = pad(shuf.slice(0, deckSlots));
    const k = keyOf(subset);
    if (seen.has(k)) continue;
    seen.add(k);
    tried++;
    const r = await Promise.resolve(simulate(subset, me, opp));
    const s = score(r);
    if (r.outcome === 'win') wins++;
    if (s > bestScore) { bestScore = s; bestSlots = subset; bestRes = r; }
  }

  process.stdout.write(JSON.stringify({
    tried, wins, pool_size: pool.length,
    original: { outcome: origRes.outcome, myHp: origRes.myHp, oppHp: origRes.oppHp, endTurn: origRes.endTurn },
    best: { outcome: bestRes.outcome, myHp: bestRes.myHp, oppHp: bestRes.oppHp, endTurn: bestRes.endTurn,
            slots: bestSlots, score: bestScore },
  }, null, 2));
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message) })));
