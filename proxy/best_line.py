# -*- coding: utf-8 -*-
"""best_line.py — adaptive, cancellable orchestration of the live best-line calc.

The live consumer submits a request (my fixture, opponent fixture, opponent board
history, round) on every state push. This engine:

  * DEDUPES ON AVAILABLE CARDS — the calc is keyed on WHICH cards I have (board +
    hand COMBINED), not how they're arranged. Rearranging the board or moving a
    card between board and hand leaves the set unchanged, so it does NOT restart a
    calc — only absorbing / merging / rerolling / drawing (which change the cards I
    have) do.
  * DEBOUNCES — a burst of pushes collapses to one calc on the latest state.
  * is ADAPTIVE — runs a FAST coarse pass first (pushed immediately so the panel
    updates within ~0.3s), then a DEEPER pass that refines and re-pushes.
  * CANCELS ON CHANGE — if the available cards change mid-calc, the in-flight result
    is discarded and the newest state is run instead. The Oracle call can't be
    interrupted, so cancellation is checked at each push point via a monotonic gen.
  * WARM-STARTS THE OPPONENT — when only MY cards changed (their board history is
    the same), the opponent's previously-found good boards seed the new search, so
    we don't re-derive what they can play from scratch.

Single background thread; only ever one calc in flight, so it never piles up on
the (single-pipe, lock-guarded) Oracle worker.
"""
import threading


def history_from_tracker(opp_tracker, opp_id, rnd, rounds=3):
    """Opponent board ids for the last `rounds` rounds, from the OpponentTracker's
    per-round store. Returns a list of card-id lists (oldest→newest), empties
    dropped."""
    out = []
    for rr in range(rnd - rounds + 1, rnd + 1):
        board = opp_tracker._by_round.get(rr, {}).get(opp_id)
        if board:
            ids = [int(c["id"]) for c in board if c and c.get("id")]
            if ids:
                out.append(ids)
    return out


def _signature(me_fx, history, rnd, my_hand):
    """Key the calc on the cards I HAVE + the opponent/round context — NOT the board
    arrangement. Available = board + hand combined, so rearranging the board (or
    moving a card between board and hand) leaves it unchanged; only a change to the
    cards themselves (absorb / merge / reroll / draw) — or my cultivation / realm /
    max-hp, or the opponent's history / round — produces a new signature."""
    board = [int(c) for c in (me_fx.get("usedCards") or []) if c]
    hand = [int(c) for c in (my_hand or []) if c]
    avail = tuple(sorted(board + hand))
    stats = (int(me_fx.get("exp", 0) or 0), int(me_fx.get("level", 0) or 0),
             int(me_fx.get("extraMaxHp", 0) or 0))
    return (avail, stats, _opp_signature(history, rnd))


def _opp_signature(history, rnd):
    """The context that determines the OPPONENT's playable boards (their history +
    round) — used to warm-start their columns when only MY cards changed."""
    return (tuple(tuple(sorted(b)) for b in (history or [])), int(rnd or 0))


class BestLineEngine:
    def __init__(self, push, debounce: float = 0.2):
        """push(result_dict): called with each best-line result (fast then final),
        on the engine thread. Result carries a `stage` of 'fast' | 'final', plus a
        `gen` so the UI can ignore a late push from a superseded request."""
        self._push = push
        self._debounce = debounce
        self._cv = threading.Condition()
        self._pending = None        # (gen, me_fx, opp_fx, history, rnd, my_hand, warm)
        self._gen = 0
        self._last_sig = None       # signature of the last SUBMITTED request
        self._warm_sig = None       # opp signature the cached columns belong to
        self._warm_cols = None      # opponent's active columns from the last calc
        self._thread = threading.Thread(target=self._run, daemon=True, name="best-line")
        self._thread.start()

    def submit(self, me_fx, opp_fx, history, rnd, my_hand=None, meta=None,
               my_history=None):
        """Register the latest request IF the available cards/context changed. A
        board rearrange (same cards) is ignored — no recalc. my_hand = my hand card
        ids. my_history = MY board ids over the last <=3 rounds (the opponent's view
        of me, used to predict their counter). meta = display-only stats merged into
        the result; NOT part of the signature."""
        if not me_fx or not opp_fx or not history:
            return
        sig = _signature(me_fx, history, rnd, my_hand)
        with self._cv:
            if sig == self._last_sig:
                return                       # same cards + context → don't restart
            self._last_sig = sig
            # Warm-start the opponent's columns if their playable set is unchanged.
            warm = self._warm_cols if _opp_signature(history, rnd) == self._warm_sig else None
            self._gen += 1
            self._pending = (self._gen, me_fx, opp_fx, list(history), rnd,
                             list(my_hand or []), warm, dict(meta or {}),
                             [list(b) for b in (my_history or [])])
            self._cv.notify()

    def _current(self, gen) -> bool:
        """True if `gen` is still the latest request (nothing newer pending)."""
        with self._cv:
            return self._gen == gen and self._pending is None

    def _run(self):
        import time
        import oracle_sim
        while True:
            # Wait until SOMETHING is pending, then debounce and grab the LATEST —
            # coalescing a burst of pushes to the newest board. Grabbing AFTER the
            # debounce (not before) is what makes the collapse correct.
            with self._cv:
                while self._pending is None:
                    self._cv.wait()
            time.sleep(self._debounce)
            with self._cv:
                if self._pending is None:
                    continue
                gen, me_fx, opp_fx, history, rnd, my_hand, warm, meta, my_history = self._pending
                self._pending = None
            try:
                # Adaptive: fast coarse pass first, then a deeper refine. Re-check
                # currency before each (potentially ~0.5s) call and before pushing.
                # warm = opponent columns from the last calc (warm-starts their side).
                fast = oracle_sim.live_best_lines(
                    me_fx, opp_fx, history, my_boards_by_round=my_history,
                    my_hand=my_hand, rnd=rnd, fast=True, opp_max_boards=8,
                    opp_seed_extra=warm)
                if fast and self._current(gen):
                    fast["stage"] = "fast"; fast["gen"] = gen; fast.update(meta)
                    self._push(fast)
                if not self._current(gen):
                    continue
                final = oracle_sim.live_best_lines(
                    me_fx, opp_fx, history, my_boards_by_round=my_history,
                    my_hand=my_hand, rnd=rnd, fast=False, opp_max_boards=24,
                    opp_seed_extra=warm)
                if final and self._current(gen):
                    final["stage"] = "final"; final["gen"] = gen; final.update(meta)
                    self._push(final)
                    # Cache the opponent's active columns to warm-start the next calc
                    # (when only my cards change, their playable set is the same).
                    cols = final.get("opp_active_boards")
                    if cols:
                        with self._cv:
                            self._warm_sig = _opp_signature(history, rnd)
                            self._warm_cols = cols
            except Exception as e:
                if self._current(gen):
                    try:
                        self._push({"error": str(e), "stage": "final", "gen": gen})
                    except Exception:
                        pass
