const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(__dirname, '..', 'web', 'yisim.bundle.js'), 'utf8');
// Inject tracing into damage_to_def calculation
const TRACE = [];
globalThis.__YISIM_TRACE__ = TRACE;
src = src.replace(
  'damage_to_def = Math.min(enemy.def, dmg);\n        damage_to_hp = dmg - damage_to_def;',
  `damage_to_def = Math.min(enemy.def, dmg); damage_to_hp = dmg - damage_to_def;
   globalThis.__YISIM_TRACE__.push({attacker: my_idx===0?'ME':'OPP', raw_dmg: dmg, enemy_def_before: enemy.def + damage_to_def, def_absorbed: damage_to_def, hp_lost: damage_to_hp, type: 'normal'});`
);
(0, eval)(src);
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = (c.name||'').startsWith('梦');
  return isDream ? { name: c.name, level: c.level, phase: c.level, isDream: true }
                 : { name: c.name, level: c.level, isDream: false };
}

(async () => {
  let buf=''; process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const me = j.me, opp = j.opponent;
  const opts = {
    mode: 'matchup', rollMode: 'average', deckSlots: me.deckSlots || 8, maxTurns: 64,
    playerState: { hp: me.hp, maxHp: me.hp, physique: me.tipo||0,
                   maxPhysique: me.max_tipo||0, cultivation: me.xiuwei||0 },
    talents: me.fates || [],
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: { hp: opp.hp, maxHp: opp.hp, physique: opp.tipo||0,
                     maxPhysique: opp.max_tipo||0, cultivation: opp.xiuwei||0 },
    opponentTalents: opp.fates || [],
  };
  const slots = (me.slots || []).map(toSlot);
  await Promise.resolve(Y.simulate(slots, opts));
  process.stdout.write(JSON.stringify(TRACE, null, 2));
})();
