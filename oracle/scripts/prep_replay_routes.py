#!/usr/bin/env python3
"""
prep_replay_routes.py — produce a per-ACTION prep-phase replay stream for the visual pre-combat action replay.

Owner: Agent 1 (pre-combat action-replay UI). Mounted into fixture_editor_server.py by Agent 2 via:
    from prep_replay_routes import router as prep_router; app.include_router(prep_router)

Why this exists: the session's ai-step returns the actions but only the FINAL state; the visual replay needs the
board/hand snapshot AFTER EACH action to animate the progression. This drives Agent 2's OWN engine — RunController +
enumerate_candidates + apply_candidate (the exact functions session_api.py uses) — and records `_run_state` after
every action, emitting the `prepReplay` model the client's PrepReplayController consumes:

  { player:{character_code, sect}, initial:Snapshot, actions:[{ index, type, animation, from, to, card,
    sourceZone, targetZone, targetSlot, stateAfter:Snapshot }] }
  Snapshot = { board:[{slot,card,active}], hand:[card], dreamStorage:[...], fates:[...], stats:{round,cultivation,...} }

Policy: a light heuristic (build the board, then ready) by default — NO neural model needed, so it's cheap and
never triggers training. `policy="ai"` can plug Agent 2's NeuralAgent in later (their ai-step already does that).

Standalone test:  uv run python tools/game-oracle/scripts/prep_replay_routes.py he6
"""
from __future__ import annotations
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))   # session_api lives here (for its serializers)

# Greedy action priority: build the board first, handle forced prompts, ready last; panels last (avoid toggle loops).
_PRIORITY = {
    "move_card": 0, "insert_card": 1, "combine_cards": 2, "absorb_card": 3, "exchange_card": 4,
    "transform": 5, "dream_fuse": 6, "select_option": 7, "ready": 9, "open_surface": 11, "close_surface": 12,
}


def _snapshot(run, gd) -> dict:
    """Map session_api._run_state(run) -> the client Snapshot shape."""
    from session_api import _run_state
    rs = _run_state(run, gd, include_hand=True)
    return {
        "board": rs.get("board") or [],
        "hand": rs.get("hand") or [],
        "dreamStorage": rs.get("dream_storage") or [],
        "fates": rs.get("selected_fates") or [],
        "stats": {k: rs.get(k) for k in ("round", "cultivation", "hp", "max_hp", "destiny", "exchange_chances", "physique", "phase")},
    }


class _RecordingPolicy:
    """A CandidatePolicy that records the UI snapshot BEFORE each decision + the picked candidate, so a full
    round (`run.run_round`) yields the per-action stream (draws happen automatically inside run_round; the AI's
    actual DECISIONS — place/absorb/exchange/upgrade/fate/ready — are what we capture).

    The default 'greedy' policy is a TERMINATING demo: resolve forced prompts, do one absorb + one exchange for
    variety, place cards into empty slots, then READY — deliberately avoiding insert_card (push), which is always
    legal and would otherwise loop forever. ('random' = the baseline; 'ai' is reserved for Agent 2's NeuralAgent.)"""
    def __init__(self, gd, policy: str, rng):
        self.gd, self.policy, self.rng = gd, policy, rng
        self.steps = []   # [{ snapshot_before, candidate }]
        self._absorbed = self._exchanged = 0

    def select(self, run, view, candidates, state_before):  # noqa: ANN001
        if self.policy == "ai":
            cand = _ai_select(run, view, candidates) or self._greedy(candidates)
        elif self.policy == "random":
            cand = self.rng.choice(candidates)
        else:
            cand = self._greedy(candidates)
        self.steps.append({"snap": _snapshot(run, self.gd), "cand": cand})
        return cand.id

    def _greedy(self, cands):
        of = lambda t: [c for c in cands if c.type.value == t]
        forced = of("select_option")
        if forced:
            return forced[0]
        if self._absorbed < 1 and of("absorb_card"):
            self._absorbed += 1; return of("absorb_card")[0]
        if self._exchanged < 1 and of("exchange_card"):
            self._exchanged += 1; return of("exchange_card")[0]
        if of("move_card"):
            return of("move_card")[0]
        if of("ready"):
            return of("ready")[0]
        # nothing left to build: prefer ready, then any non-looping/non-panel action
        nonloop = [c for c in cands if c.type.value not in ("insert_card", "open_surface", "close_surface")]
        return (nonloop or cands)[0]


def build_prep_replay(character_code: str = "he6", seed: int = 0, policy: str = "greedy") -> dict:
    """Play one player's round-1 preparation (via run_round) and emit the per-action replay stream."""
    from yixian.data.game_data import GameData
    from yixian.engine.session import RunController
    from yixian.engine.rules import heavenly_derivation_rules
    from session_api import _candidate_to_dict

    gd = GameData.load()
    run = RunController(player_id="ai", character_code=character_code, sect=character_code[:2],
                        game_data=gd, rules=heavenly_derivation_rules(), rng=random.Random(seed))
    run.start()
    pol = _RecordingPolicy(gd, policy, random.Random(seed ^ 0x5151))
    run.run_round(pol)               # drives the whole prep; pol records each decision + the snapshot before it
    final = _snapshot(run, gd)

    steps = pol.steps
    initial = steps[0]["snap"] if steps else final
    actions = []
    for i, st in enumerate(steps):
        d = _candidate_to_dict(st["cand"], gd)
        rep = d.get("replay") or {}
        actions.append({
            "index": i,
            "type": d.get("type"),
            "animation": rep.get("animation") or _default_anim(d.get("type")),
            "from": rep.get("from"),
            "to": rep.get("to"),
            "card": (d.get("source") or {}).get("card_info") or (d.get("target") or {}).get("card_info"),
            "sourceZone": (d.get("source") or {}).get("zone"),
            "targetZone": (d.get("target") or {}).get("zone"),
            "targetSlot": (d.get("target") or {}).get("slot"),
            "stateAfter": steps[i + 1]["snap"] if i + 1 < len(steps) else final,   # before next decision = after this one
        })
    return {"player": {"character_code": character_code, "sect": character_code[:2]}, "initial": initial, "actions": actions}


def _ai_select(run, view, candidates):
    """Pick a candidate with Agent 2's trained NeuralAgent (the same model + encoders ai-step uses). Returns None
    on any failure (no torch / no model / encode error) so the caller falls back to the greedy demo policy."""
    try:
        import torch
        from session_api import _load_ai
        from yixian.training.state_encoder import GameObservation, encode_candidates
        agent, device = _load_ai()
        _ci = lambda c: (int(c) if c not in (None, "") and str(c).lstrip("-").isdigit() else 0)
        obs = GameObservation(
            sect={"sw": 1, "dx": 2, "fe": 3, "he": 4}.get(run.sect, 0),
            phase=int(run.phase), round_number=run.round_number, cultivation=run.cultivation,
            hp=run.hp, max_hp=run.max_hp, destiny=run.destiny, exchange_chances=run.exchange_chances,
            physique=getattr(run, "physique", 0),
            hand=[_ci(c) for c in run.hand], board=[_ci(c) for c in run.board],
            selected_fates=list(run.selected_fates), active_surface=view.active_surface.value,
        )
        with torch.no_grad():
            state_vec = agent.encoder([obs])
            feats, mask = encode_candidates(candidates, agent.encoder.card_embed, device)
            logits = agent.policy(state_vec, feats.unsqueeze(0), mask.unsqueeze(0)).squeeze(0)[:len(candidates)]
            if torch.isnan(logits).any() or torch.isinf(logits).all():
                return None
            idx = int(torch.softmax(logits, dim=0).argmax().item())
        return candidates[idx]
    except Exception as e:  # noqa: BLE001
        print(f"[prep_replay] ai policy fallback ({type(e).__name__}: {e})")
        return None


def _default_anim(action_type):
    return {"select_option": "select_option", "ready": "click_ready", "combine_cards": "combine",
            "dream_fuse": "dream_fuse", "transform": "bianyi"}.get(action_type, "drag_card")


# ── FastAPI router (Agent 2 mounts this) ──────────────────────────────────────────────────────────────
try:
    from fastapi import APIRouter
    router = APIRouter()

    @router.get("/api/prep-replay")
    def api_prep_replay(character: str = "he6", seed: int = 0, policy: str = "greedy"):
        """Build a prep-phase action replay for one fresh run (round 1). policy: greedy|random|ai."""
        return build_prep_replay(character, seed, policy)
except ImportError:
    router = None


if __name__ == "__main__":
    cc = sys.argv[1] if len(sys.argv) > 1 else "he6"
    rep = build_prep_replay(cc, seed=int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    print(f"prep replay: {cc}  initial hand={len(rep['initial']['hand'])}  actions={len(rep['actions'])}")
    for a in rep["actions"]:
        nm = (a["card"] or {}).get("name", "")
        print(f"  #{a['index']:2} {a['type']:14} {a['from'] or '':>9} -> {a['to'] or '':<11} {nm}")
    fin = rep["actions"][-1]["stateAfter"] if rep["actions"] else rep["initial"]
    filled = sum(1 for b in fin["board"] if b.get("card"))
    print(f"final: board filled={filled}  hand={len(fin['hand'])}  cultivation={fin['stats'].get('cultivation')}")
