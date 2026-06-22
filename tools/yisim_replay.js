// yisim_replay.js — verbose per-turn replay using the rebuilt yisim bundle.
'use strict';
const fs = require('fs');
const path = require('path');

const BUNDLE = path.join(__dirname, '..', 'web', 'yisim.bundle.js');
(0, eval)(fs.readFileSync(BUNDLE, 'utf8'));
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  // Real card levels only go 1-3. BL.usedCards reports "lv4"/"lv5" which are
  // really phases — the card text/effect at phase 3+ stays at the lv3 swogi
  // entry. Clamp non-dream level to 3 so fuzzy resolves to the right card
  // (otherwise lv4/5 falls through to a wrong-card match).
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

(async () => {
  let buf = '';
  process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const round = j.round;
  const me = round.me, opp = round.opponent;
  if (Y.ready) { try { await Promise.resolve(Y.ready); } catch (e) {} }

  const meSlotsRaw = j.custom_slots ? j.custom_slots : (me.slots || []);
  const meSlots = meSlotsRaw.map(toSlot);

  const result = await Promise.resolve(Y.simulate(meSlots, {
    mode: 'matchup',
    rollMode: 'average',
    deckSlots: me.deckSlots || meSlots.length || 8,
    maxTurns: j.maxTurns || 15,
    playerState: buildPlayerState(me),
    talents: Array.isArray(me.fates) ? me.fates : [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: buildPlayerState(opp),
    opponentTalents: Array.isArray(opp.fates) ? opp.fates : [],
    verbose: true,
  }));

  process.stdout.write(JSON.stringify(result));
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message) })));
