const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(__dirname, '..', 'web', 'yisim.bundle.js'), 'utf8');
const TRACE = [];
let phase = 'init';
globalThis.__YISIM_TRACE__ = TRACE;
globalThis.__YISIM_PHASE_GET__ = () => phase;
globalThis.__YISIM_PHASE_SET__ = (p) => { phase = p; };

// Hook the damage block (normal path)
src = src.replace(
  'damage_to_def = Math.min(enemy.def, dmg);\n        damage_to_hp = dmg - damage_to_def;',
  `damage_to_def = Math.min(enemy.def, dmg); damage_to_hp = dmg - damage_to_def;
   globalThis.__YISIM_TRACE__.push({phase: globalThis.__YISIM_PHASE_GET__(), raw_dmg: dmg, enemy_def_before: enemy.def + damage_to_def, def_absorbed: damage_to_def, hp_lost: damage_to_hp, enemy_hp_after: enemy.hp - damage_to_hp});`
);
// reduce_idx_hp catches all hp reductions (including internal injury)
src = src.replace(
  /^(\s*reduce_idx_hp\(idx, amt\) \{)$/m,
  `$1\n    globalThis.__YISIM_TRACE__.push({phase: globalThis.__YISIM_PHASE_GET__(), hp_reduction: amt, target_idx: idx});`
);

(0, eval)(src);
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = (c.name||'').startsWith('梦');
  return isDream ? { name: c.name, level: c.level, phase: c.level, isDream: true }
                 : { name: c.name, level: c.level, isDream: false };
}

// Mark phase by overriding simulate with a wrapped version that uses runSingleSimulation
// Actually wrap Y.simulate to mark turns. But simulate has internal swapping…
// Easier: directly use the runSingleSimulation via swappers. For now, just mark
// based on what we see — count attack events between sim_turn calls.

(async () => {
  let buf=''; process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const me = j.me, opp = j.opponent;
  const opts = {
    mode: 'matchup', rollMode: 'high', deckSlots: me.deckSlots || 8, maxTurns: 64,
    playerState: { hp: me.hp, maxHp: me.hp, physique: me.tipo||0,
                   maxPhysique: me.max_tipo||0, cultivation: me.xiuwei||0 },
    talents: me.fates || [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: { hp: opp.hp, maxHp: opp.hp, physique: opp.tipo||0,
                     maxPhysique: opp.max_tipo||0, cultivation: opp.xiuwei||0 },
    opponentTalents: opp.fates || [],
  };
  const slots = (me.slots || []).map(toSlot);
  const r = await Promise.resolve(Y.simulate(slots, opts));
  process.stdout.write(JSON.stringify({trace: TRACE, perTurnDamage: r.perTurnDamage,
    perTurnTaken: r.perTurnTaken, endTurn: r.endTurn, outcome: r.outcome,
    myHp: r.myHp, oppHp: r.oppHp}, null, 2));
})();
