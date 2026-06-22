
const fs = require('fs');
(0, eval)(fs.readFileSync('web/yisim.bundle.js', 'utf8'));
const Y = globalThis.yisim;
function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = c.name.startsWith('梦');
  const lv = c.level || 1;
  return isDream ? {name: c.name, level: Math.min(lv,5), phase: lv, isDream: true}
                 : {name: c.name, level: Math.min(lv,3), isDream: false};
}
(async () => {
  let buf = '';
  process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  const me = j.me, opp = j.opponent;
  if (Y.ready) await Y.ready;
  const r = Y.simulate(me.slots.map(toSlot), {
    mode: 'matchup', rollMode: 'average', deckSlots: 8, maxTurns: 64,
    playerState: {hp: me.hp, maxHp: me.hp, physique: me.tipo, maxPhysique: me.max_tipo, cultivation: me.xiuwei},
    talents: me.fates,
    opponentSlots: opp.slots.map(toSlot),
    opponentState: {hp: opp.hp, maxHp: opp.hp, physique: opp.tipo, maxPhysique: opp.max_tipo, cultivation: opp.xiuwei},
    opponentTalents: opp.fates,
  });
  console.log("typeof r:", typeof r);
  console.log("r keys:", Object.keys(r || {}));
  console.log("r:", JSON.stringify(r, null, 2).slice(0, 2000));
})();
