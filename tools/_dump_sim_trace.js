const fs = require('fs');
const path = require('path');
const BUNDLE = path.join(__dirname, '..', 'web', 'yisim.bundle.js');
(0, eval)(fs.readFileSync(BUNDLE, 'utf8'));
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

  // Hook into GameState's deal_damage_inner to dump (turn, attacker, opp.def before, dmg, opp.def after)
  // and into sim_turn to log turn boundaries.
  const trace = [];
  // Find GameState class via Y exports
  const orig = globalThis.GameState && globalThis.GameState.prototype;
  if (orig && orig.deal_damage_inner) {
    const orig_fn = orig.deal_damage_inner;
    orig.deal_damage_inner = function(dmg, is_atk, my_idx, is_extra, smash) {
      const enemy = this.players[1 - my_idx];
      const me_p = this.players[my_idx];
      const before = enemy.def;
      const hp_before = enemy.hp;
      const ret = orig_fn.call(this, dmg, is_atk, my_idx, is_extra, smash);
      trace.push({
        attacker: my_idx === 0 ? 'ME' : 'OPP',
        dmg, before_def: before, after_def: enemy.def,
        hp_change: hp_before - enemy.hp,
        is_atk,
      });
      return ret;
    };
  }
  if (orig && orig.sim_turn) {
    const orig_turn = orig.sim_turn;
    orig.sim_turn = function(turn, my_idx) {
      const enemy = this.players[1 - my_idx];
      const me_p = this.players[my_idx];
      trace.push({ turn: `T${turn} ${my_idx === 0 ? 'ME' : 'OPP'} plays`,
                   me_hp: me_p.hp, me_def: me_p.def, opp_hp: enemy.hp, opp_def: enemy.def });
      return orig_turn.call(this, turn, my_idx);
    };
  }

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
  process.stdout.write(JSON.stringify(trace, null, 2));
})();
