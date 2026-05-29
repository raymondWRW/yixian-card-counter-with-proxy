// yisim_entry.js — browser entry for the yi-sim damage engine.
//
// Ported from the old Electron app's yisim_adapter.js, with the Node file I/O
// (fs/path/pathToFileURL) replaced by static ES imports so it bundles for the
// webview. Exposes globalThis.yisim = { ready, simulate }.
//
// Bundled by build_yisim.mjs (esbuild) into web/yisim.bundle.js.

import { GameState, guess_character, ready as engineReady } from './gamestate_full_nolog.js';
import { card_name_to_id_fuzzy, ready as fuzzyReady } from './card_name_to_id_fuzzy.js';
import { swogi as SWOGI, names_json as NAMES } from './card_info.js';

const DEFAULT_ROLL_MODE = 'average';
const AVERAGE_SIM_RUNS = 100;

let lastSimulationKey = null;
let lastSimulationResult = null;
let cardNameTranslationsCache = null;
let exactDetectedCardIdsCache = null;
let swogiKeySetCache = null;

const DREAM_NAME_ALIASES = { '梦·凝意决': '梦·凝意诀' };

function normalizeDetectedName(name) {
  const normalized = (name || '').replace(/[•·]/g, '·').trim();
  return DREAM_NAME_ALIASES[normalized] || normalized;
}

function loadCardNameTranslations() {
  if (cardNameTranslationsCache) return cardNameTranslationsCache;
  const translations = {};
  if (Array.isArray(NAMES)) {
    NAMES.forEach((entry) => {
      const chineseName = normalizeDetectedName(entry?.namecn);
      const englishName = typeof entry?.name === 'string' ? entry.name.trim() : '';
      if (!chineseName || !englishName || translations[chineseName]) return;
      translations[chineseName] = englishName;
    });
  }
  cardNameTranslationsCache = translations;
  return cardNameTranslationsCache;
}

function loadExactDetectedCardIds() {
  if (exactDetectedCardIdsCache) return exactDetectedCardIdsCache;
  const exactIds = {};
  const baseNames = {};
  if (Array.isArray(NAMES)) {
    NAMES.forEach((entry) => {
      const id = String(entry?.id || '');
      const chineseName = normalizeDetectedName(entry?.namecn);
      if (!id || !chineseName) return;
      baseNames[id] = chineseName;
    });
  }
  Object.keys(SWOGI || {}).forEach((cardId) => {
    const level = Number.parseInt(cardId.slice(-1), 10);
    if (!Number.isFinite(level)) return;
    const baseId = `${cardId.slice(0, -1)}1`;
    const chineseName = baseNames[cardId] || baseNames[baseId];
    if (!chineseName) return;
    exactIds[`${chineseName} (level ${level})`] = cardId;
    if (cardId.endsWith('1')) exactIds[chineseName] = cardId;
  });
  exactDetectedCardIdsCache = exactIds;
  return exactDetectedCardIdsCache;
}

function loadSwogiKeySet() {
  if (swogiKeySetCache) return swogiKeySetCache;
  swogiKeySetCache = new Set(Object.keys(SWOGI || {}));
  return swogiKeySetCache;
}

function swogiIdExists(id) {
  if (id == null) return false;
  return loadSwogiKeySet().has(String(id));
}

function findSwogiIdForPrefixLevel(prefix, level) {
  const candidate = `${prefix}${level}`;
  return swogiIdExists(candidate) ? candidate : null;
}

function getMaxLevelForPrefix(prefix) {
  const keys = loadSwogiKeySet();
  let maxLevel = 0;
  for (const key of keys) {
    if (key.length === prefix.length + 1 && key.startsWith(prefix)) {
      const level = Number.parseInt(key.slice(-1), 10);
      if (Number.isFinite(level) && level > maxLevel) maxLevel = level;
    }
  }
  return maxLevel;
}

const RUNTIME_KEY_PLACEHOLDER = /\{n\}/g;

function resolveRuntimeKey(runtimeKey, position) {
  if (!runtimeKey || typeof runtimeKey !== 'string') return null;
  if (!runtimeKey.includes('{n}')) return runtimeKey;
  if (!Number.isFinite(Number(position))) return null;
  return runtimeKey.replace(RUNTIME_KEY_PLACEHOLDER, String(Number(position)));
}

function normalizeTalents(rawTalents) {
  if (!Array.isArray(rawTalents)) return [];
  return rawTalents
    .filter((talent) => talent && talent.detected)
    .map((talent) => ({
      position: Number(talent.position) || null,
      // R26: keep `phase` (= pick order, 1-based) on the normalized object.
      // Not consumed by today's hardcoded effects, but lets future
      // phase-aware logic — or callers inspecting `result.talentIntegration`
      // — see which phase variant of a multi-phase fate was picked.
      phase: Number(talent.phase) || Number(talent.position) || null,
      name: typeof talent.name === 'string' ? talent.name : '',
      simulationKind: talent.simulationKind || 'non-combat-or-unsupported',
      runtimeKey: resolveRuntimeKey(talent.runtimeKey, talent.position),
      grantedCardBaseIds: Array.isArray(talent.grantedCardBaseIds)
        ? talent.grantedCardBaseIds.map(Number).filter(Number.isFinite)
        : [],
    }))
    .filter((talent) => talent.name);
}

function buildEmptyTalentIntegration() {
  return {
    appliedRuntimeTalents: [], representedByCards: [],
    unsupportedDirectTalents: [], ignoredNonCombatTalents: [], partial: false,
  };
}

function finalizeTalentIntegration(integration) {
  return { ...integration, partial: integration.unsupportedDirectTalents.length > 0 };
}

const SOLITARY_VOID_BASE_PREFIX = '21501';
const SOLITARY_VOID_LEFT_PREFIX = '21601';
const SOLITARY_VOID_RIGHT_PREFIX = '21701';

function applySolitaryVoidTransform(playerCards, normalizedSlots) {
  const indexOfAnchor = playerCards.findIndex((id) => String(id || '').startsWith(SOLITARY_VOID_BASE_PREFIX));
  if (indexOfAnchor < 0) return { applied: false };
  const anchorId = String(playerCards[indexOfAnchor]);
  const anchorLevel = Number.parseInt(anchorId.slice(-1), 10) || 1;
  const anchorMaxLevel = getMaxLevelForPrefix(SOLITARY_VOID_BASE_PREFIX) || anchorLevel;
  const isSlotEmpty = (index) => (index < 0 || index >= playerCards.length) ? false : !normalizedSlots[index];
  const isSideAvailable = (index) => (index < 0 || index >= playerCards.length) ? false : isSlotEmpty(index);
  let pendingLevel = anchorLevel;
  const leftIndex = indexOfAnchor - 1;
  if (isSideAvailable(leftIndex)) {
    const leftId = findSwogiIdForPrefixLevel(SOLITARY_VOID_LEFT_PREFIX, 1);
    if (leftId) playerCards[leftIndex] = leftId; else pendingLevel = Math.min(anchorMaxLevel, pendingLevel + 1);
  } else pendingLevel = Math.min(anchorMaxLevel, pendingLevel + 1);
  const rightIndex = indexOfAnchor + 1;
  if (isSideAvailable(rightIndex)) {
    const rightId = findSwogiIdForPrefixLevel(SOLITARY_VOID_RIGHT_PREFIX, 1);
    if (rightId) playerCards[rightIndex] = rightId; else pendingLevel = Math.min(anchorMaxLevel, pendingLevel + 1);
  } else pendingLevel = Math.min(anchorMaxLevel, pendingLevel + 1);
  if (pendingLevel !== anchorLevel) {
    const upgradedId = findSwogiIdForPrefixLevel(SOLITARY_VOID_BASE_PREFIX, pendingLevel);
    if (upgradedId) playerCards[indexOfAnchor] = upgradedId;
  }
  return { applied: true };
}

function prepareTalentIntegration(normalized, probePlayer, playerCards, normalizedSlots) {
  const integration = buildEmptyTalentIntegration();
  const runtimeWrites = [];
  const suppressedRuntimeKeys = new Set();
  const suppressedNames = new Set();
  const hasAttainQi = normalized.some((talent) => talent.name === 'Attain Qi');
  if (hasAttainQi) {
    const mortalBody = normalized.find((talent) => talent.name === 'Mortal Body');
    if (mortalBody) {
      suppressedNames.add('Mortal Body');
      if (mortalBody.runtimeKey) suppressedRuntimeKeys.add(mortalBody.runtimeKey);
    }
  }
  for (const talent of normalized) {
    if (suppressedNames.has(talent.name)) continue;
    if (talent.simulationKind === 'non-combat-or-unsupported') { integration.ignoredNonCombatTalents.push(talent.name); continue; }
    if (talent.simulationKind === 'card-grant') { integration.representedByCards.push(talent.name); continue; }
    if (talent.simulationKind === 'runtime-stack') {
      const key = talent.runtimeKey;
      if (key && !suppressedRuntimeKeys.has(key) && Object.prototype.hasOwnProperty.call(probePlayer, key)) {
        runtimeWrites.push({ key, value: 1 });
        integration.appliedRuntimeTalents.push(talent.name);
      } else integration.unsupportedDirectTalents.push(talent.name);
      continue;
    }
    if (talent.simulationKind === 'transform') {
      if (talent.name === 'Attain Qi') {
        const surgeKey = 'surge_of_qi_stacks';
        if (Object.prototype.hasOwnProperty.call(probePlayer, surgeKey)) {
          runtimeWrites.push({ key: surgeKey, value: 1 });
          integration.appliedRuntimeTalents.push(talent.name);
        } else integration.unsupportedDirectTalents.push(talent.name);
        continue;
      }
      if (talent.name === 'Solitary Void Golden Scroll') {
        const result = applySolitaryVoidTransform(playerCards, normalizedSlots);
        if (result.applied) integration.appliedRuntimeTalents.push(talent.name);
        else integration.unsupportedDirectTalents.push(talent.name);
        continue;
      }
      integration.unsupportedDirectTalents.push(talent.name);
      continue;
    }
    integration.unsupportedDirectTalents.push(talent.name);
  }
  return { integration: finalizeTalentIntegration(integration), runtimeWrites };
}

function isDreamSlot(slot) {
  if (!slot) return false;
  if (slot.isDream) return true;
  return normalizeDetectedName(slot.name).startsWith('梦');
}

function formatDetectedCard(slot) {
  if (!slot) return '普通攻击';
  const normalizedName = normalizeDetectedName(slot.name);
  const phaseLevel = Number.parseInt(slot?.phase, 10);
  const fallbackLevel = Number.parseInt(slot?.level, 10);
  const level = isDreamSlot(slot)
    ? (Number.isFinite(phaseLevel) && phaseLevel > 0 ? phaseLevel : 1)
    : (Number.isFinite(fallbackLevel) && fallbackLevel > 0 ? fallbackLevel : 1);
  return `${normalizedName} (level ${level})`;
}

function resolveDetectedCardId(slot, fuzzy) {
  const formatted = formatDetectedCard(slot);
  const exactDetectedCardIds = loadExactDetectedCardIds();
  if (exactDetectedCardIds[formatted]) return exactDetectedCardIds[formatted];
  if (isDreamSlot(slot)) throw new Error(`yi-sim does not support detected dream card "${formatted}"`);
  try {
    return fuzzy(formatted);
  } catch (error) {
    throw new Error(`yi-sim could not map detected card "${formatted}"`);
  }
}

function normalizeRollMode(rollMode) {
  return (rollMode === 'high' || rollMode === 'low' || rollMode === 'average') ? rollMode : DEFAULT_ROLL_MODE;
}

function normalizeDeckSlots(deckSlots) {
  const parsed = Number.parseInt(deckSlots, 10);
  if (!Number.isFinite(parsed)) return 8;
  return Math.max(0, Math.min(8, parsed));
}

function normalizePlayerState(playerState = {}) {
  const source = playerState && typeof playerState === 'object' ? playerState : {};
  const n = {
    hp: Number(source.hp), maxHp: Number(source.maxHp),
    physique: Number(source.physique), maxPhysique: Number(source.maxPhysique),
    cultivation: Number(source.cultivation), character: source.character || null,
  };
  return {
    hp: Number.isFinite(n.hp) ? n.hp : 110,
    maxHp: Number.isFinite(n.maxHp) ? n.maxHp : null,
    physique: Number.isFinite(n.physique) ? n.physique : 0,
    maxPhysique: Number.isFinite(n.maxPhysique) ? n.maxPhysique : 0,
    cultivation: Number.isFinite(n.cultivation) ? n.cultivation : 100,
    character: n.character,
  };
}

function buildEmptyResult(error = null) {
  return {
    first8Turns: null, perTurnDamage: [], cumulativeDamage: [],
    damageTaken: null, perTurnTaken: [], cumulativeTaken: [],
    verdict: null, turnsSimulated: 0,
    outcome: 'undecided', endTurn: null,
    lastSlotMe: null, lastSlotOpp: null,
    playerCharacter: null, talentIntegration: buildEmptyTalentIntegration(), error,
  };
}

// Build player + opponent. If opponentSlots is provided (real matchup), the
// opponent is built from those cards + opponentState; otherwise a generic
// dummy opponent is used (solo mode, as in the old app).
function buildPlayers(normalizedSlots, fuzzy, guessChar, options = {}) {
  const playerState = normalizePlayerState(options.playerState);
  const playerCards = normalizedSlots.map((slot) => resolveDetectedCardId(slot, fuzzy));

  const player = {
    hp: playerState.hp, physique: playerState.physique,
    max_physique: playerState.maxPhysique, cultivation: playerState.cultivation,
    cards: playerCards,
  };
  player.max_hp = Number.isFinite(playerState.maxHp)
    ? Math.max(playerState.maxHp, player.hp) : (player.hp + player.physique);
  player.character = guessChar(player);

  let opponent;
  if (Array.isArray(options.opponentSlots) && options.opponentSlots.some(Boolean)) {
    const oppState = normalizePlayerState(options.opponentState);
    const oppCards = options.opponentSlots.map((slot) => {
      try { return resolveDetectedCardId(slot, fuzzy); }
      catch { return resolveDetectedCardId(null, fuzzy); }
    });
    opponent = {
      hp: oppState.hp, physique: oppState.physique, max_physique: oppState.maxPhysique,
      cultivation: oppState.cultivation, cards: oppCards, _real: true,
    };
    opponent.max_hp = Number.isFinite(oppState.maxHp)
      ? Math.max(oppState.maxHp, opponent.hp) : (opponent.hp + opponent.physique);
  } else {
    opponent = {
      hp: 9999, physique: 0, max_physique: 0, cultivation: 0,
      cards: Array(Math.max(1, normalizedSlots.length)).fill(resolveDetectedCardId(null, fuzzy)),
      _real: false,
    };
    opponent.max_hp = opponent.hp + opponent.physique;
  }
  opponent.character = guessChar(opponent);
  return { player, opponent };
}

// Full-length series — does NOT truncate at 8. Cumulative damage covers every
// simulated turn; UI is responsible for slicing the visual list to 8.
function fullSeries(values) {
  const padded = values.slice();
  const cumulative = [];
  let running = 0;
  padded.forEach((d) => { running += d; cumulative.push(running); });
  return { perTurn: padded, cumulative, total: cumulative[cumulative.length - 1] ?? 0 };
}

function applyRollModeOverrides(game, rollMode) {
  if (rollMode !== 'high' && rollMode !== 'low') return;
  game.rand_range = function (lo, hi) {
    if (this.trigger_hexagram(0)) return hi;
    this.used_randomness = true;
    return rollMode === 'high' ? hi : lo;
  };
  game.if_c_pct = function (c) {
    if (this.trigger_hexagram(0)) return true;
    this.used_randomness = true;
    return rollMode === 'high';
  };
}

// One simulation. Runs up to `maxTurns` (default 64) "rounds" of you-then-opp
// until game_over fires. Returns raw per-turn damage dealt/taken, the outcome,
// the turn it was decided on, and the index of the LAST card slot YOU played
// (used by the UI to highlight that slot win/lose).
//   outcome: 'win' (opponent dead) | 'lose' (you dead) | 'draw' | 'undecided'
function runSingleSimulation(player, opponent, rollMode, runtimeWrites = [], maxTurns = 64, oppRuntimeWrites = []) {
  const game = new GameState();
  Object.assign(game.players[0], { ...player, cards: [...player.cards] });
  Object.assign(game.players[1], { ...opponent, cards: [...opponent.cards] });
  for (const write of runtimeWrites) {
    if (write && write.key) game.players[0][write.key] = write.value;
  }
  // R26: opponent runtime-stack talents seed at sim start the same way ME's
  // do. Only ever non-empty in matchup mode (solo's dummy opponent gets no
  // talents from the UI). prepareTalentIntegration already gated each write
  // by `hasOwnProperty(probeOpponent, key)`, so unknown keys never get here.
  for (const write of oppRuntimeWrites) {
    if (write && write.key) game.players[1][write.key] = write.value;
  }
  applyRollModeOverrides(game, rollMode);
  // Solo mode: replace the dummy opponent's cards with inert mystery seeds so
  // it never fights back. Real matchup keeps the opponent's actual cards.
  if (!opponent._real) {
    const MYSTERY_SEED_ID = '362021';
    game.players[1].cards = Array(Math.max(1, game.players[1].cards.length)).fill(MYSTERY_SEED_ID);
  }
  game.start_of_game_setup();

  const perTurnDealt = [];
  const perTurnTaken = [];
  let endTurn = null;
  let lastSlotMe = null;       // slot you played most recently
  let lastSlotOpp = null;      // slot opponent played most recently
  const myDeckLen = (game.players[0].cards || []).length || 1;
  const oppDeckLen = (game.players[1].cards || []).length || 1;
  for (let turnIndex = 0; turnIndex < maxTurns; turnIndex += 1) {
    const oppBefore = game.players[1].hp ?? 0;
    const myBefore = game.players[0].hp ?? 0;
    // The slot about to play = next_card_index BEFORE sim_turn.
    const myAbout = game.players[0].next_card_index ?? 0;
    game.sim_turn();                       // your turn → you hit the opponent
    lastSlotMe = myAbout % myDeckLen;
    if (game.game_over) {
      perTurnDealt.push(Math.max(0, oppBefore - (game.players[1].hp ?? oppBefore)));
      perTurnTaken.push(0);
      endTurn = turnIndex + 1;
      break;
    }
    game.swap_players();
    // After swap, players[0] is the opponent — record THEIR next_card_index.
    const oppAbout = game.players[0].next_card_index ?? 0;
    game.sim_turn();                       // opponent's turn → they hit you
    lastSlotOpp = oppAbout % oppDeckLen;
    game.swap_players();
    perTurnDealt.push(Math.max(0, oppBefore - (game.players[1].hp ?? oppBefore)));
    perTurnTaken.push(Math.max(0, myBefore - (game.players[0].hp ?? myBefore)));
    if (game.game_over) { endTurn = turnIndex + 1; break; }
  }

  const myHp = game.players[0].hp ?? 0;
  const oppHp = game.players[1].hp ?? 0;
  let outcome = 'undecided';
  if (game.game_over) {
    if (oppHp <= 0 && myHp > 0) outcome = 'win';
    else if (myHp <= 0 && oppHp > 0) outcome = 'lose';
    else outcome = 'draw';
  }
  return { perTurnDealt, perTurnTaken, outcome, endTurn, myHp, oppHp, lastSlotMe, lastSlotOpp };
}

// Aggregate one or many runs into the result shape the UI consumes.
function summarizeRuns(runs) {
  const n = runs.length || 1;
  // Aggregate per-turn damage over the longest run; unused turns sum to 0.
  const maxLen = runs.reduce((m, r) => Math.max(m, r.perTurnDealt.length), 0);
  const avgDealt = [];
  const avgTaken = [];
  for (let t = 0; t < maxLen; t += 1) {
    avgDealt.push(Math.round(runs.reduce((s, r) => s + (r.perTurnDealt[t] || 0), 0) / n));
    avgTaken.push(Math.round(runs.reduce((s, r) => s + (r.perTurnTaken[t] || 0), 0) / n));
  }
  const dealt = fullSeries(avgDealt);
  const taken = fullSeries(avgTaken);
  const wins = runs.filter((r) => r.outcome === 'win');
  const loses = runs.filter((r) => r.outcome === 'lose');
  const decided = runs.filter((r) => r.endTurn != null);
  const avgEndTurn = decided.length
    ? Math.round(decided.reduce((s, r) => s + r.endTurn, 0) / decided.length) : null;
  // Pick the most-common outcome across runs as the displayed result.
  let outcome = 'undecided';
  if (wins.length > loses.length && wins.length > n - wins.length - loses.length) outcome = 'win';
  else if (loses.length > wins.length && loses.length > n - wins.length - loses.length) outcome = 'lose';
  else if (decided.length > 0 && wins.length === loses.length) outcome = 'draw';
  // Last slot played: take any decided run's last slots; runs are deterministic
  // per rollMode/average, so all runs share the same slot order.
  const sampleRun = decided[0] || runs[0] || {};
  return {
    perTurnDamage: dealt.perTurn,
    cumulativeDamage: dealt.cumulative,
    first8Turns: dealt.cumulative[Math.min(7, dealt.cumulative.length - 1)] ?? 0,
    perTurnTaken: taken.perTurn,
    cumulativeTaken: taken.cumulative,
    damageTaken: taken.total,
    turnsSimulated: dealt.perTurn.length,
    endTurn: avgEndTurn,
    outcome,
    lastSlotMe: sampleRun.lastSlotMe ?? null,
    lastSlotOpp: sampleRun.lastSlotOpp ?? null,
    verdict: {
      winRate: wins.length / n,
      loseRate: loses.length / n,
      avgEndTurn,
    },
  };
}

let _runtimeReady = null;
function runtimeReady() {
  if (!_runtimeReady) _runtimeReady = Promise.all([engineReady, fuzzyReady]);
  return _runtimeReady;
}

async function simulate(slots, options = {}) {
  await runtimeReady();
  const rollMode = normalizeRollMode(options.rollMode);
  const deckSlots = normalizeDeckSlots(options.deckSlots);
  // Cap the simulation length. Default 64; clamp to [1, 64].
  const maxTurns = Math.max(1, Math.min(64, Number(options.maxTurns) || 64));
  const playerState = normalizePlayerState(options.playerState);
  const normalizedSlots = (slots || []).slice(0, deckSlots);
  while (normalizedSlots.length < deckSlots) normalizedSlots.push(null);
  const normalizedTalents = normalizeTalents(options.talents);
  const opponentSlots = (options.mode === 'matchup' && Array.isArray(options.opponentSlots))
    ? options.opponentSlots : null;
  // R26: in matchup mode the opponent's fates flow through the same
  // normalization pipeline as the player's. In solo mode the dummy opponent
  // gets no talents — feeding talents into prepareTalentIntegration for a
  // mystery-seed deck would be a no-op anyway (no runtimeKeys to apply).
  const normalizedOppTalents = (options.mode === 'matchup')
    ? normalizeTalents(options.opponentTalents) : [];

  const cacheKey = JSON.stringify({
    deckSlots, rollMode, maxTurns,
    playerState: { hp: playerState.hp, maxHp: playerState.maxHp, physique: playerState.physique,
      maxPhysique: playerState.maxPhysique, cultivation: playerState.cultivation, character: playerState.character },
    slots: normalizedSlots.map((s) => s ? { name: s.name, level: s.level, phase: s.phase ?? null, isDream: !!s.isDream } : null),
    opp: opponentSlots ? opponentSlots.map((s) => s ? { name: s.name, level: s.level } : null) : null,
    oppState: options.opponentState || null,
    talents: normalizedTalents.map((t) => ({ position: t.position, phase: t.phase, name: t.name, simulationKind: t.simulationKind, runtimeKey: t.runtimeKey, grantedCardBaseIds: t.grantedCardBaseIds })),
    oppTalents: normalizedOppTalents.map((t) => ({ position: t.position, phase: t.phase, name: t.name, simulationKind: t.simulationKind, runtimeKey: t.runtimeKey, grantedCardBaseIds: t.grantedCardBaseIds })),
  });
  if (cacheKey === lastSimulationKey && lastSimulationResult) return lastSimulationResult;

  try {
    if (deckSlots <= 0) {
      lastSimulationKey = cacheKey;
      lastSimulationResult = buildEmptyResult();
      return lastSimulationResult;
    }
    const { player, opponent } = buildPlayers(normalizedSlots, card_name_to_id_fuzzy, guess_character, {
      playerState, opponentSlots, opponentState: options.opponentState,
    });
    const probeGame = new GameState();
    const probePlayer = probeGame.players[0];
    const probeOpponent = probeGame.players[1];
    const { integration: talentIntegration, runtimeWrites } =
      prepareTalentIntegration(normalizedTalents, probePlayer, player.cards, normalizedSlots);
    // R26: same call for the opponent. `opponent.cards` is the matchup
    // opponent's actual deck; in solo mode opponent.cards is the dummy seed
    // deck and `normalizedOppTalents` is empty so this is a cheap no-op.
    const { integration: opponentTalentIntegration, runtimeWrites: oppRuntimeWrites } =
      normalizedOppTalents.length
        ? prepareTalentIntegration(normalizedOppTalents, probeOpponent, opponent.cards, opponentSlots || [])
        : { integration: null, runtimeWrites: [] };

    const runs = rollMode === 'average'
      ? Array.from({ length: AVERAGE_SIM_RUNS },
          () => runSingleSimulation(player, opponent, DEFAULT_ROLL_MODE, runtimeWrites, maxTurns, oppRuntimeWrites))
      : [runSingleSimulation(player, opponent, rollMode, runtimeWrites, maxTurns, oppRuntimeWrites)];
    const summary = summarizeRuns(runs);
    // The verdict / back-damage / win-lose outcome only make sense against a
    // real opponent. In solo mode the dummy opponent never fights back, so
    // suppress those fields.
    if (!opponent._real) {
      summary.verdict = null;
      summary.damageTaken = null;
      summary.perTurnTaken = [];
      summary.cumulativeTaken = [];
      summary.outcome = 'undecided';
      summary.endTurn = null;
      summary.lastSlotOpp = null;
    }

    const result = { ...summary, playerCharacter: playerState.character || player.character,
      opponentCharacter: opponent._real ? opponent.character : null,
      matchup: !!opponent._real, talentIntegration, opponentTalentIntegration, error: null };
    lastSimulationKey = cacheKey;
    lastSimulationResult = result;
    return result;
  } catch (error) {
    const failed = buildEmptyResult(error && error.message ? error.message : String(error));
    lastSimulationKey = cacheKey;
    lastSimulationResult = failed;
    return failed;
  }
}

const yisim = { ready: runtimeReady, simulate, loadCardNameTranslations };
globalThis.yisim = yisim;
export { yisim, simulate };
