const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(__dirname, '..', 'web', 'yisim.bundle.js'), 'utf8');
const T = [];
globalThis.__T__ = T;
src = src.replace(/play_card\(card_id, idx\) \{/,
  `play_card(card_id, idx) {
    globalThis.__T__.push({event: 'play', who: this.players[0].__marker, card_id: String(card_id), idx,
      my_hp: this.players[0].hp, my_def: this.players[0].def,
      enemy_hp: this.players[1].hp, enemy_def: this.players[1].def});`);
src = src.replace(/swap_players\(\) \{/,
  `swap_players() {
    globalThis.__T__.push({event: 'swap'});`);
src = src.replace(/return\s*\{\s*player,\s*opponent\s*\};/,
  'player.__marker="ME"; opponent.__marker="OPP"; return { player, opponent };');
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
  process.stdout.write(JSON.stringify({trace: T, me_slots: opts.opponentSlots, opp_slots: opts.opponentSlots}, null, 2));
})();
