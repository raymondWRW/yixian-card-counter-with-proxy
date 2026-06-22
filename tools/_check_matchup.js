const fs = require('fs');
const path = require('path');
let src = fs.readFileSync(path.join(__dirname, '..', 'web', 'yisim.bundle.js'), 'utf8');
// Hook buildPlayers to log _real flag — that tells us solo vs matchup
src = src.replace(
  /_real:\s*true/,
  `_real: true, __DEBUG_IS_MATCHUP: true`
);
src = src.replace(
  /_real:\s*false/,
  `_real: false, __DEBUG_IS_SOLO: true`
);
// Also expose game.players via a hook on simulate completion
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

  // Try BOTH solo and matchup with identical state — they should differ
  const baseOpts = {
    rollMode: 'high', deckSlots: me.deckSlots || 8, maxTurns: 64,
    playerState: { hp: me.hp, maxHp: me.hp, physique: me.tipo||0,
                   maxPhysique: me.max_tipo||0, cultivation: me.xiuwei||0 },
    talents: me.fates || [],
  };
  const slots = (me.slots || []).map(toSlot);

  const soloR = await Y.simulate(slots, { ...baseOpts, mode: 'solo' });
  const matchupR = await Y.simulate(slots, { ...baseOpts,
    mode: 'matchup',
    opponentSlots: (opp.slots || []).map(toSlot),
    opponentState: { hp: opp.hp, maxHp: opp.hp, physique: opp.tipo||0,
                     maxPhysique: opp.max_tipo||0, cultivation: opp.xiuwei||0 },
    opponentTalents: opp.fates || [],
  });

  process.stdout.write(JSON.stringify({
    solo: { outcome: soloR.outcome, endTurn: soloR.endTurn,
            perTurnDamage: soloR.perTurnDamage.map(x => Math.round(x)),
            perTurnTaken: soloR.perTurnTaken.map(x => Math.round(x)),
            oppHp: soloR.oppHp, matchup_flag: soloR.matchup },
    matchup: { outcome: matchupR.outcome, endTurn: matchupR.endTurn,
               perTurnDamage: matchupR.perTurnDamage.map(x => Math.round(x)),
               perTurnTaken: matchupR.perTurnTaken.map(x => Math.round(x)),
               oppHp: matchupR.oppHp, matchup_flag: matchupR.matchup },
  }, null, 2));
})();
