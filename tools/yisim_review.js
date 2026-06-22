// yisim_review.js — try permutations of a lost round's board to find a winning
// arrangement. Reads round JSON (as written to battle_log/HHMMSS_rN.json) from
// stdin. Runs yisim in MATCHUP mode (ME vs the exact opponent board), tries up
// to N permutations, stops at the first win.
//
// stdin:  { round: <round-json>, max_perms: 300 }
// stdout: { win: bool, outcome: "win"|"lose"|"draw"|"undecided",
//           tried: N, winning_slots: [{name,level}|null,...]|null,
//           original_outcome: "...", original_dmg_diff: number }
'use strict';
const fs = require('fs');
const path = require('path');

const BUNDLE = path.join(__dirname, '..', 'web', 'yisim.bundle.js');
(0, eval)(fs.readFileSync(BUNDLE, 'utf8'));
const Y = globalThis.yisim;

function toSlot(c) {
  if (!c || !c.name) return null;
  const isDream = typeof c.name === 'string' && c.name.startsWith('梦');
  // Real card levels only go 1-3 in yisim's swogi. BL.usedCards reports lv4/5
  // which are PHASES; the underlying card data lives at lv3. Clamp non-dream
  // levels to 3 (otherwise fuzzy lookup mis-resolves to a wrong card).
  const rawLevel = c.level || 1;
  return isDream
    ? { name: c.name, level: Math.min(rawLevel, 5), phase: rawLevel, isDream: true }
    : { name: c.name, level: Math.min(rawLevel, 3), isDream: false };
}

function buildPlayerState(side) {
  // The recorded per-round JSON stores `hp`, `tipo`, `max_tipo`, `xiuwei`.
  // yisim's playerState wants {hp, maxHp, physique, maxPhysique, cultivation}.
  return {
    hp: side.hp,
    maxHp: side.hp,
    physique: side.tipo || 0,
    maxPhysique: side.max_tipo || side.tipo || 0,
    cultivation: side.xiuwei || 0,
  };
}

// Compact talents to the shape yisim's normalizeTalents accepts. The recorded
// `fates` array is already in the right shape (position/phase/name/
// simulationKind/runtimeKey/grantedCardBaseIds) — just pass through.
function buildTalents(side) {
  return Array.isArray(side.fates) ? side.fates : [];
}

function simulate(meSlots, meSide, oppSide) {
  const opts = {
    mode: 'matchup',
    rollMode: 'average',
    deckSlots: meSide.deckSlots || meSlots.length || 8,
    maxTurns: 64,
    playerState: buildPlayerState(meSide),
    talents: buildTalents(meSide),
    opponentSlots: (oppSide.slots || []).map(toSlot),
    opponentState: buildPlayerState(oppSide),
    opponentTalents: buildTalents(oppSide),
  };
  return Y.simulate(meSlots, opts);
}

function shuffleInPlace(a) {
  // Fisher-Yates over the non-null entries only — empty slots (普通攻击) stay
  // randomized too, which preserves the deckSlots count.
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
}

function keyOf(slots) {
  return slots.map(s => s ? `${s.name}@${s.level || 1}` : '_').join('|');
}

(async () => {
  let buf = '';
  process.stdin.on('data', d => buf += d);
  await new Promise(r => process.stdin.on('end', r));

  let j;
  try { j = JSON.parse(buf); }
  catch (e) { process.stdout.write('{"error":"bad json"}'); return; }

  const round = j.round || {};
  const me = round.me || {};
  const opp = round.opponent || {};
  const meSlotsOrig = (me.slots || []).map(toSlot);
  if (!meSlotsOrig.length) {
    process.stdout.write(JSON.stringify({ error: 'no me.slots' }));
    return;
  }
  if (!(opp.slots && opp.slots.length)) {
    process.stdout.write(JSON.stringify({ error: 'no opponent.slots' }));
    return;
  }

  // Pool of candidate cards = the played board + every hand card the player
  // could have played instead. Nulls (empty board slots) are kept since the
  // player may also choose to leave a slot empty (→ Normal Attack).
  const hand = Array.isArray(me.hand) ? me.hand.map(toSlot).filter(Boolean) : [];
  const deckSlots = me.deckSlots || meSlotsOrig.length || 8;
  // Effective pool: every card the player owned at battle start.
  const pool = meSlotsOrig.filter(Boolean).concat(hand);

  if (Y.ready) { try { await Promise.resolve(Y.ready); } catch (e) {} }

  // Re-run the original arrangement just to record its sim outcome (and
  // closest damage gap). We do NOT short-circuit if yisim happens to score
  // the original as 'win' — the player lost in-game, so the original is
  // unhelpful as a "solution". Always search for a DIFFERENT arrangement.
  const originalRes = await Promise.resolve(simulate(meSlotsOrig.slice(), me, opp));
  const origOutcome = originalRes && originalRes.outcome;
  const origDmgGap = originalRes && originalRes.damageGap;
  // Track the original by key so search results that happen to match it are
  // rejected (we want a different recipe than what the player tried).
  const ORIGINAL_KEY = keyOf(meSlotsOrig);

  // Search strategy:
  //  · permutations of the played board only (fast, no new cards)
  //  · then board-with-hand-swap (replace each board card with each hand card)
  //  · then random sampling of deckSlots-sized subsets of the full pool
  // Stop at the first arrangement yisim scores as a win.
  const maxPerms = Math.max(20, Math.min(2000, j.max_perms || 500));
  const seen = new Set([keyOf(meSlotsOrig)]);
  let bestGap = origDmgGap;
  let bestSlots = meSlotsOrig;

  async function trySlots(slots, i) {
    const k = keyOf(slots);
    if (seen.has(k)) return null;
    seen.add(k);
    const r = await Promise.resolve(simulate(slots, me, opp));
    if (r && r.outcome === 'win') {
      return r;
    }
    if (r && typeof r.damageGap === 'number' &&
        (bestGap == null || r.damageGap < bestGap)) {
      bestGap = r.damageGap;
      bestSlots = slots;
    }
    return null;
  }

  // Pad/truncate to deckSlots size with nulls.
  function pad(arr) {
    const out = arr.slice(0, deckSlots);
    while (out.length < deckSlots) out.push(null);
    return out;
  }

  let tried = 1; // counted the original
  // Phase A — permutations of the original board only (cheap, often enough).
  const phaseA = Math.min(maxPerms / 2, 200);
  for (let i = 0; i < phaseA; i++) {
    const perm = meSlotsOrig.slice();
    shuffleInPlace(perm);
    tried++;
    const win = await trySlots(perm, tried);
    if (win) {
      process.stdout.write(JSON.stringify({
        win: true, outcome: 'win', tried,
        original_outcome: origOutcome,
        original_dmg_gap: origDmgGap,
        winning_slots: perm,
        pool_size: pool.length,
        end_turn: win.endTurn,
        used_hand: false,
      }));
      return;
    }
  }

  // Phase B — single-card swap: replace one board card with one hand card.
  for (let i = 0; i < meSlotsOrig.length && hand.length; i++) {
    for (const hc of hand) {
      const swapped = meSlotsOrig.slice();
      swapped[i] = hc;
      tried++;
      const win = await trySlots(swapped, tried);
      if (win) {
        process.stdout.write(JSON.stringify({
          win: true, outcome: 'win', tried,
          original_outcome: origOutcome,
          original_dmg_gap: origDmgGap,
          winning_slots: swapped,
          pool_size: pool.length,
          end_turn: win.endTurn,
          used_hand: true,
        }));
        return;
      }
      // Also try shuffles of the swapped board.
      for (let s = 0; s < 5; s++) {
        const shuffled = swapped.slice();
        shuffleInPlace(shuffled);
        tried++;
        const win2 = await trySlots(shuffled, tried);
        if (win2) {
          process.stdout.write(JSON.stringify({
            win: true, outcome: 'win', tried,
            original_outcome: origOutcome,
            original_dmg_gap: origDmgGap,
            winning_slots: shuffled,
            pool_size: pool.length,
            end_turn: win2.endTurn,
            used_hand: true,
          }));
          return;
        }
      }
    }
  }

  // Phase C — random deckSlots-sized subsets of the full pool.
  const remaining = Math.max(0, maxPerms - tried);
  for (let i = 0; i < remaining; i++) {
    const shuf = pool.slice();
    shuffleInPlace(shuf);
    const subset = pad(shuf.slice(0, deckSlots));
    tried++;
    const win = await trySlots(subset, tried);
    if (win) {
      process.stdout.write(JSON.stringify({
        win: true, outcome: 'win', tried,
        original_outcome: origOutcome,
        original_dmg_gap: origDmgGap,
        winning_slots: subset,
        pool_size: pool.length,
        end_turn: win.endTurn,
        used_hand: true,
      }));
      return;
    }
  }

  process.stdout.write(JSON.stringify({
    win: false, tried,
    original_outcome: origOutcome,
    original_dmg_gap: origDmgGap,
    closest_dmg_gap: bestGap,
    pool_size: pool.length,
  }));
})().catch(e => process.stdout.write(JSON.stringify({ error: String(e && e.message) })));
