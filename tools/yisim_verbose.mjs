// yisim_verbose.mjs — runs a yisim simulation and captures per-turn state
// (cards played, debuff stacks, hp) for both players. Uses ESM imports of
// yisim engine internals directly.
import { GameState, ready as engineReady } from '../vendor/yisim-master/gamestate_full_nolog.js';
import { card_name_to_id_fuzzy, ready as fuzzyReady } from '../vendor/yisim-master/card_name_to_id_fuzzy.js';
import { swogi as SWOGI, names_json as NAMES } from '../vendor/yisim-master/card_info.js';

await Promise.all([engineReady, fuzzyReady]);

function resolveSlotId(slot) {
  if (!slot || !slot.name) return null;
  const isDream = typeof slot.name === 'string' && slot.name.startsWith('梦');
  if (isDream) {
    const baseId = card_name_to_id_fuzzy(slot.name);
    if (!baseId) return null;
    const phase = slot.phase || slot.level || 1;
    return baseId.slice(0, -1) + String(phase);
  }
  const baseId = card_name_to_id_fuzzy(slot.name);
  if (!baseId) return null;
  const lv = slot.level || 1;
  return baseId.slice(0, -1) + String(lv);
}

function buildPlayer(side, isReal = true) {
  const cards = (side.slots || []).map(resolveSlotId).filter(Boolean);
  if (cards.length === 0) cards.push('601011'); // basic atk
  return {
    hp: side.hp, max_hp: side.hp,
    cards, deck: cards.slice(),
    cultivation: side.xiuwei || 0,
    physique: side.tipo || 0, max_physique: side.max_tipo || 0,
    _real: isReal,
  };
}

function loadInput() {
  return new Promise((resolve) => {
    let buf = '';
    process.stdin.on('data', d => buf += d);
    process.stdin.on('end', () => resolve(JSON.parse(buf)));
  });
}

const j = await loadInput();
const round = j.round;
const me = round.me, opp = round.opponent;
const maxTurns = j.maxTurns || 15;
const meSlots = j.custom_slots ? j.custom_slots : me.slots;

const game = new GameState();
Object.assign(game.players[0], buildPlayer({ ...me, slots: meSlots }, true));
Object.assign(game.players[1], buildPlayer(opp, true));
game.start_of_game_setup();

function nameOf(cid) {
  if (!cid) return null;
  // names_json has [{name, namecn, id}]
  const entry = (Array.isArray(NAMES) ? NAMES : []).find(e => String(e.id) === String(cid));
  if (entry) return entry.namecn || entry.name || cid;
  return cid;
}

function snapPlayer(p, prevHp, prevDeckIdx) {
  return {
    hp: p.hp,
    def: p.def || 0,
    internal_injury: p.internal_injury || 0,
    weaken: p.weaken || 0,
    flaw: p.flaw || 0,
    deck_index: p.next_card_index || 0,
    cards_played_this_turn: [], // filled in by diff
    dmg_taken_this_turn: Math.max(0, (prevHp ?? p.hp) - p.hp),
  };
}

function cardsPlayedThisTurn(p, deckIdxBefore, deckLen) {
  const out = [];
  const after = p.next_card_index || 0;
  // The player can play multiple cards per turn (chase mechanics).
  for (let i = deckIdxBefore; i < after; i++) {
    const cid = p.cards[i % deckLen];
    out.push({ slot: i % deckLen, name: nameOf(cid), id: cid });
  }
  return out;
}

const meDeckLen = (game.players[0].cards || []).length || 1;
const oppDeckLen = (game.players[1].cards || []).length || 1;
const turns = [];

for (let t = 0; t < maxTurns; t++) {
  if (game.game_over) break;
  const meHpBefore = game.players[0].hp;
  const oppHpBefore = game.players[1].hp;
  const meDeckBefore = game.players[0].next_card_index || 0;
  const oppDeckBefore = game.players[1].next_card_index || 0;

  // ME plays
  game.sim_turn();
  const mePlayed = cardsPlayedThisTurn(game.players[0], meDeckBefore, meDeckLen);
  if (game.game_over) {
    turns.push({
      turn: t + 1,
      me_played: mePlayed,
      opp_played: [],
      me: snapPlayer(game.players[0], meHpBefore),
      opp: snapPlayer(game.players[1], oppHpBefore),
      game_over: true,
    });
    break;
  }

  // OPP plays
  game.swap_players();
  game.sim_turn();
  const oppPlayed = cardsPlayedThisTurn(game.players[0], oppDeckBefore, oppDeckLen);
  game.swap_players();

  turns.push({
    turn: t + 1,
    me_played: mePlayed,
    opp_played: oppPlayed,
    me: snapPlayer(game.players[0], meHpBefore),
    opp: snapPlayer(game.players[1], oppHpBefore),
    game_over: game.game_over,
  });
  if (game.game_over) break;
}

process.stdout.write(JSON.stringify({
  turns,
  final: {
    me_hp: game.players[0].hp,
    opp_hp: game.players[1].hp,
    game_over: game.game_over,
    winner: game.players[0].hp > 0 && game.players[1].hp <= 0 ? 'me' :
            game.players[1].hp > 0 && game.players[0].hp <= 0 ? 'opp' :
            'undecided',
  },
}, null, 2));
