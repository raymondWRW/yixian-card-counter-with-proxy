# -*- coding: utf-8 -*-
"""best_line.py — adaptive, cancellable orchestration of the live best-line calc.

The live consumer submits a request (my fixture, opponent fixture, opponent board
history, round) on every state push. This engine:

  * DEBOUNCES — a burst of pushes (a card placement often emits several) collapses
    to one calc on the latest state.
  * is ADAPTIVE — runs a FAST coarse pass first (pushed immediately so the panel
    updates within ~0.3s), then a DEEPER pass that refines and re-pushes.
  * CANCELS ON CHANGE — if the board changes mid-calc (reroll / absorption / a new
    GameStatus), the in-flight result is discarded and the newest request is run
    instead (requirement: our cards are always the CURRENT cards). The Oracle call
    itself can't be interrupted, so cancellation is checked at each push point via
    a monotonic generation counter.

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


class BestLineEngine:
    def __init__(self, push, debounce: float = 0.2):
        """push(result_dict): called with each best-line result (fast then final),
        on the engine thread. Result carries a `stage` of 'fast' | 'final', plus a
        `gen` so the UI can ignore a late push from a superseded request."""
        self._push = push
        self._debounce = debounce
        self._cv = threading.Condition()
        self._pending = None        # (gen, me_fx, opp_fx, history, rnd)
        self._gen = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="best-line")
        self._thread.start()

    def submit(self, me_fx, opp_fx, history, rnd, my_hand=None):
        """Register the latest request, superseding any earlier one. Cheap; called
        from the consumer on every push. my_hand = my hand card ids (candidate
        lines consider playing these, not just rearranging the board)."""
        if not me_fx or not opp_fx or not history:
            return
        with self._cv:
            self._gen += 1
            self._pending = (self._gen, me_fx, opp_fx, list(history), rnd,
                             list(my_hand or []))
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
                gen, me_fx, opp_fx, history, rnd, my_hand = self._pending
                self._pending = None
            try:
                # Adaptive: fast coarse pass first, then a deeper refine. Re-check
                # currency before each (potentially ~0.5s) call and before pushing.
                fast = oracle_sim.live_best_lines(
                    me_fx, opp_fx, history, my_hand=my_hand, rnd=rnd,
                    fast=True, opp_max_boards=8)
                if fast and self._current(gen):
                    fast["stage"] = "fast"; fast["gen"] = gen
                    self._push(fast)
                if not self._current(gen):
                    continue
                final = oracle_sim.live_best_lines(
                    me_fx, opp_fx, history, my_hand=my_hand, rnd=rnd,
                    fast=False, opp_max_boards=24)
                if final and self._current(gen):
                    final["stage"] = "final"; final["gen"] = gen
                    self._push(final)
            except Exception as e:
                if self._current(gen):
                    try:
                        self._push({"error": str(e), "stage": "final", "gen": gen})
                    except Exception:
                        pass
