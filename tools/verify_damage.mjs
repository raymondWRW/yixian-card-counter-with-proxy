// verify_damage.mjs
// Run yisim's matchup simulation for every round in an input rounds.json
// and write the per-round result to an output file.
//
// Usage:  node tools/verify_damage.mjs <rounds_in.json> <result_out.json>

import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

const [, , roundsPath, outPath] = process.argv;
if (!roundsPath || !outPath) {
  console.error('usage: node verify_damage.mjs <rounds_in.json> <result_out.json>');
  process.exit(2);
}

const bundle = readFileSync(path.join(ROOT, 'web', 'yisim.bundle.js'), 'utf8');
(0, eval)(bundle);
if (!globalThis.yisim) {
  console.error('yisim not attached to globalThis after eval');
  process.exit(1);
}

const rounds = JSON.parse(readFileSync(roundsPath, 'utf8'));
await globalThis.yisim.ready();

const out = [];
for (const r of rounds) {
  const me = r.me;
  const opp = r.opponent;
  const deckSlots = me.deckSlots || 8;
  const oppDeckSlots = opp.deckSlots || deckSlots;
  // Turn-order from cultivation (per YiXianPai rule): higher → goes first;
  // tied → random tie-break (yisim averages both orderings).
  // Last-stand for the second player ONLY fires on cultivation tie (not
  // when one player has higher cult — even by 1). Tested R8 confirmation.
  const meCult = me.xiuwei || 0;
  const oppCult = opp.xiuwei || 0;
  let turnOrder;
  if (meCult > oppCult) turnOrder = 'me-first';
  else if (meCult < oppCult) turnOrder = 'opp-first';
  else turnOrder = 'tied';
  const opts = {
    rollMode: 'average',
    deckSlots,
    maxTurns: 64,
    mode: 'matchup',
    turnOrder,
    lastStandSecond: turnOrder === 'tied',
    playerState: {
      hp: me.hp, maxHp: me.hp,
      physique: me.tipo || 0, maxPhysique: me.max_tipo || me.tipo || 0,
      cultivation: meCult,
    },
    talents: me.fates || [],   // already talent objects from _fates_to_talents
    opponentSlots: (opp.slots || []).slice(0, oppDeckSlots),
    opponentState: {
      hp: opp.hp, maxHp: opp.hp,
      physique: opp.tipo || 0, maxPhysique: opp.max_tipo || opp.tipo || 0,
      cultivation: oppCult,
    },
    opponentTalents: opp.fates || [],  // already talent objects from _fates_to_talents
  };
  let result, hi, lo;
  try {
    result = await globalThis.yisim.simulate(me.slots, opts);
    // RNG-detection probe: high vs low rollMode. If the battle has any
    // random rolls (rand_range / if_c_pct / if_n_pct), the two extremes
    // produce different outcomes or totals. Same boards, same fates,
    // same turn order — only the random rolls differ.
    hi = await globalThis.yisim.simulate(me.slots, {...opts, rollMode: 'high'});
    lo = await globalThis.yisim.simulate(me.slots, {...opts, rollMode: 'low'});
  } catch (e) {
    result = { error: String(e) };
  }
  const sumOrZero = arr => (arr || []).reduce((a, b) => a + b, 0);
  const hasRng = !!(hi && lo) && (
    hi.outcome !== lo.outcome
    || sumOrZero(hi.perTurnDamage) !== sumOrZero(lo.perTurnDamage)
    || sumOrZero(hi.perTurnTaken) !== sumOrZero(lo.perTurnTaken)
  );
  out.push({
    round: r.round,
    error: result?.error || null,
    first8Turns: result?.first8Turns,
    perTurnDamage: (result?.perTurnDamage || []),
    perTurnTaken: (result?.perTurnTaken || []),
    cumulativeDamage: (result?.cumulativeDamage || []),
    cumulativeTaken: (result?.cumulativeTaken || []),
    outcome: result?.outcome,
    endTurn: result?.endTurn,
    myHp: result?.myHp,
    oppHp: result?.oppHp,
    turnOrder,
    hasRng,
    rngHi: hi ? { outcome: hi.outcome, dealt: sumOrZero(hi.perTurnDamage), taken: sumOrZero(hi.perTurnTaken) } : null,
    rngLo: lo ? { outcome: lo.outcome, dealt: sumOrZero(lo.perTurnDamage), taken: sumOrZero(lo.perTurnTaken) } : null,
  });
  const rngFlag = hasRng ? ' 🎲RNG' : '';
  console.error(`R${r.round}: my=${result?.first8Turns}  outcome=${result?.outcome}  endTurn=${result?.endTurn}  turnOrder=${turnOrder}${rngFlag}`);
}

writeFileSync(outPath, JSON.stringify(out, null, 2), 'utf8');
console.error(`\nWrote ${out.length} round results to ${outPath}`);
