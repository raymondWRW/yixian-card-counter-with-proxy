
const fs = require('fs');
(0, eval)(fs.readFileSync('web/yisim.bundle.js', 'utf8'));
const Y = globalThis.yisim;
function toSlot(c){if(!c||!c.name)return null;return {name:c.name,level:Math.min(c.level||1,3),isDream:false};}
(async () => {
  let buf=''; process.stdin.on('data', d => buf+=d);
  await new Promise(r => process.stdin.on('end', r));
  const j = JSON.parse(buf);
  if (Y.ready) await Y.ready;
  const r = await Promise.resolve(Y.simulate(j.slots.map(toSlot), {
    mode: 'solo',
    rollMode: 'average',
    deckSlots: 8,
    maxTurns: 8,
    playerState: {hp: j.hp, maxHp: j.hp, physique: j.tipo, maxPhysique: j.maxTipo, cultivation: j.cult},
    talents: [],
  }));
  process.stdout.write(JSON.stringify(r));
})();
