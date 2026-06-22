const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(__dirname, '..', 'web', 'yisim.bundle.js'), 'utf8');
// Hook the buildPlayers return to expose opponent.cards
src = src.replace(
  /return\s*\{\s*player,\s*opponent\s*\};/,
  'globalThis.__YISIM_OPP_CARDS__ = opponent.cards.slice(); globalThis.__YISIM_OPP_INFO__ = {hp: opponent.hp, max_hp: opponent.max_hp, physique: opponent.physique, max_physique: opponent.max_physique, _real: opponent._real}; return { player, opponent };'
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
  await Y.simulate(slots, opts);
  process.stdout.write(JSON.stringify({
    opp_info: globalThis.__YISIM_OPP_INFO__,
    opp_cards: globalThis.__YISIM_OPP_CARDS__,
    opp_slots_passed_in: opts.opponentSlots,
  }, null, 2));
})();
