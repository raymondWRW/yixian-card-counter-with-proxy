
const fs = require('fs');
(0, eval)(fs.readFileSync('web/yisim.bundle.js', 'utf8'));
const Y = globalThis.yisim;
function toSlot(c){if(!c||!c.name)return null;return {name:c.name,level:Math.min(c.level||1,3),isDream:false};}
(async () => {
  let buf=''; process.stdin.on('data', d => buf+=d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  if (Y.ready) await Y.ready;
  for (const mode of ['high', 'average', 'low']) {
    const r = await Promise.resolve(Y.simulate(j.slots.map(toSlot), {
      mode: 'matchup', rollMode: mode, deckSlots: 8, maxTurns: 64,
      playerState: {hp: j.me.hp, maxHp: j.me.hp, physique: j.me.tipo, maxPhysique: j.me.max_tipo, cultivation: j.me.xiuwei},
      talents: j.me.fates,
      opponentSlots: j.opp.slots.map(toSlot),
      opponentState: {hp: j.opp.hp, maxHp: j.opp.hp, physique: j.opp.tipo, maxPhysique: j.opp.max_tipo, cultivation: j.opp.xiuwei},
      opponentTalents: j.opp.fates,
    }));
    console.log(`${mode.padEnd(8)} outcome=${r.outcome.padEnd(10)} endT=${r.endTurn}  myHp=${r.myHp} oppHp=${r.oppHp}`);
  }
})();
