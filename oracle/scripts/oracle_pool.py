#!/usr/bin/env python3
"""
oracle_pool.py — version-keyed WARM worker pool for the native Oracle.

The Oracle's combat is ~2ms/battle, but a cold `--run-fixture` pays ~0.9-1.3s of DLL-patch + config
deserialize every call (see oracle-perf-profile). A worker started with `--serve` pays that ONCE, then
answers one fixture JSON per stdin line with one result JSON per stdout line at full speed. This module
manages a {version -> warm worker} map, lazily spawning a worker pinned to each version's snapshot
(`--store data/versions/<V>`) and routing each fixture to the worker for its version.

  from oracle_pool import OraclePool
  pool = OraclePool()
  result = pool.run(fixture_dict)                  # routes by fixture['version'] (or default)
  pool.close()

CLI benchmark:  uv run python tools/game-oracle/scripts/oracle_pool.py --bench [N] [--version V]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

# Rewired for the standalone layout: <oracle>/scripts/ -> <oracle>/ is one level up.
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
ORACLE_EXE = os.environ.get("ORACLE_EXE") or os.path.join(
    ROOT, "Oracle", "bin", "Release", "net8.0", "Oracle.exe")
VERSIONS = os.path.join(ROOT, "data", "versions")


class OracleWorker:
    """One warm `--serve` subprocess, optionally pinned to a version snapshot via --store."""

    def __init__(self, version: str | None = None, store: str | None = None, ready_timeout: float = 30.0):
        self.version = version
        cmd = [ORACLE_EXE, "--serve"]
        if store:
            cmd += ["--store", store]
        env = dict(os.environ)
        env.setdefault("ORACLE_MAXDEPTH", "1000")
        # BELOW_NORMAL priority (Windows): the calc must never outcompete the GAME
        # for CPU. Combat sims happily pin a core for the whole search window on
        # stack-heavy comps; at normal priority that lags the game the tool is
        # assisting. Below-normal keeps the game smooth and the Oracle still gets
        # every idle cycle (the calc just finishes a bit later under load).
        flags = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if os.name == "nt" else 0
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, cwd=os.path.dirname(ORACLE_EXE), env=env,
            creationflags=flags,
        )
        # Drain the one-time startup banner until the readiness marker.
        t0 = time.time()
        while True:
            if time.time() - t0 > ready_timeout:
                raise TimeoutError("oracle --serve worker did not become ready")
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("oracle --serve worker exited during startup")
            if '"serve"' in line and "ready" in line:
                break

    def run(self, fixture: dict) -> dict:
        """Send one fixture, return its result dict."""
        self.proc.stdin.write(json.dumps(fixture) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("oracle --serve worker closed mid-request")
            line = line.strip()
            if not line.startswith("{"):
                continue  # skip any stray non-JSON line
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "engine" in obj or "error" in obj:
                return obj

    def close(self) -> None:
        try:
            self.proc.stdin.write("quit\n")
            self.proc.stdin.flush()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class OraclePool:
    """Lazy {version -> warm worker}. Routes each fixture to the worker pinned to its version."""

    def __init__(self, default_version: str | None = None):
        self.workers: dict[str, OracleWorker] = {}
        self.default_version = default_version

    def _store_for(self, version: str) -> str | None:
        store = os.path.join(VERSIONS, version)
        return store if os.path.isdir(store) else None

    def worker_for(self, version: str | None) -> OracleWorker:
        key = version or "__live__"
        if key not in self.workers:
            self.workers[key] = OracleWorker(version=version, store=self._store_for(version) if version else None)
        return self.workers[key]

    def run(self, fixture: dict, version: str | None = None) -> dict:
        v = version or fixture.get("version") or self.default_version
        return self.worker_for(v).run(fixture)

    def close(self) -> None:
        for w in self.workers.values():
            w.close()
        self.workers.clear()


def run_batch(fixtures: list[dict], n_workers: int, version: str | None = None) -> list[dict]:
    """Run `fixtures` across `n_workers` WARM workers in parallel, returning results in input order.

    Each worker is a separate process (isolated state — no cross-stream bleed), pinned to `version`'s
    snapshot if given. Work is pulled from a shared queue so a slow battle on one worker doesn't stall the
    rest. Python threads only block on the worker pipes; the actual combat runs in the C# subprocesses,
    so this scales with cores. This is the bulk/training throughput path.
    """
    import queue as _queue
    import threading

    store = None
    if version:
        s = os.path.join(VERSIONS, version)
        store = s if os.path.isdir(s) else None

    work: "_queue.Queue[tuple[int, dict]]" = _queue.Queue()
    for i, fx in enumerate(fixtures):
        work.put((i, fx))
    results: list[dict | None] = [None] * len(fixtures)

    def worker_loop():
        w = OracleWorker(version=version, store=store)
        try:
            while True:
                try:
                    idx, fx = work.get_nowait()
                except _queue.Empty:
                    return
                try:
                    # Bulk path: no front-end, so ask the worker to skip the per-turn log (shrinks the
                    # response payload — the dominant transport cost). UI callers keep the default (log on).
                    results[idx] = w.run({**fx, "wantLog": False})
                except Exception as e:
                    results[idx] = {"engine": "oracle", "ok": False, "error": str(e)}
        finally:
            w.close()

    threads = [threading.Thread(target=worker_loop) for _ in range(max(1, n_workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results  # type: ignore


def run_cached(base: dict, variants: list[dict], n_workers: int, version: str | None = None) -> list[dict]:
    """Stat-cache board search: prime each worker ONCE with `base`'s stat, then run each variant as
    {id, **variant} sending only the deck edits — not the whole stat — over the pipe.

    `base` must carry `id` and `stat`. Each `variant` is merged onto {id: base id, wantLog: False}, e.g.
    {"p1Cards": [...]}. The worker re-parses the cached stat fresh per run (bit-exact), applies the deck
    override, and runs. Transport-optimized path for the exponential board search.
    """
    import queue as _queue
    import threading

    store = None
    if version:
        s = os.path.join(VERSIONS, version)
        store = s if os.path.isdir(s) else None
    base_id = base.get("id") or "base"
    prime_msg = {"id": base_id, "stat": base["stat"], "prime": True}

    work: "_queue.Queue[tuple[int, dict]]" = _queue.Queue()
    for i, v in enumerate(variants):
        work.put((i, v))
    results: list[dict | None] = [None] * len(variants)

    def worker_loop():
        w = OracleWorker(version=version, store=store)
        try:
            ack = w.run(prime_msg)
            if not ack.get("primed"):
                raise RuntimeError(f"prime failed: {ack}")
            while True:
                try:
                    idx, v = work.get_nowait()
                except _queue.Empty:
                    return
                try:
                    results[idx] = w.run({"id": base_id, "wantLog": False, **v})
                except Exception as e:
                    results[idx] = {"engine": "oracle", "ok": False, "error": str(e)}
        finally:
            w.close()

    threads = [threading.Thread(target=worker_loop) for _ in range(max(1, n_workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results  # type: ignore


def run_board_batch(base: dict, boards: list[list[int]], n_workers: int, version: str | None = None,
                    side: str = "p1", chunk: int = 500) -> list[tuple[int, int]]:
    """IN-PROCESS batch board search: prime each worker once, then send boards in CHUNKS — each chunk is
    evaluated entirely in-process on the cached br (ONE IPC round-trip per chunk, not per board). Returns
    [(hpDelta, turns), ...] aligned to `boards`. This eliminates the per-board IPC overhead.
    """
    import queue as _queue
    import threading

    store = None
    if version:
        s = os.path.join(VERSIONS, version)
        store = s if os.path.isdir(s) else None
    base_id = base.get("id") or "base"
    prime_msg = {"id": base_id, "stat": base["stat"], "prime": True}

    # Each queue item carries a retry count so a chunk dropped by a dying worker is re-queued, not lost.
    work: "_queue.Queue[tuple[int, list, int]]" = _queue.Queue()
    for i in range(0, len(boards), chunk):
        work.put((i, boards[i:i + chunk], 0))
    results: list[tuple[int, int] | None] = [None] * len(boards)

    def worker_loop():
        try:
            w = OracleWorker(version=version, store=store)
            ack = w.run(prime_msg)
            if not ack.get("primed"):
                raise RuntimeError(f"prime failed: {ack}")
        except Exception:
            return                                          # can't even start; let other workers carry the queue
        try:
            while True:
                try:
                    start, ch, tries = work.get_nowait()
                except _queue.Empty:
                    return
                try:
                    resp = w.run({"id": base_id, "boards": ch, "side": side})
                    rows = resp.get("results", [])
                    if len(rows) != len(ch):
                        raise RuntimeError(f"short batch: {len(rows)}/{len(ch)}")
                    for j, row in enumerate(rows):
                        results[start + j] = (row[0], row[1])
                except Exception:
                    # Worker likely died mid-chunk: re-queue (bounded) so another worker retries it, then
                    # respawn this one. If respawn fails or retries exhausted, those boards stay None.
                    if tries < 2:
                        work.put((start, ch, tries + 1))
                    try:
                        w.close()
                    except Exception:
                        pass
                    try:
                        w = OracleWorker(version=version, store=store)
                        if not w.run(prime_msg).get("primed"):
                            return
                    except Exception:
                        return
        finally:
            w.close()

    threads = [threading.Thread(target=worker_loop) for _ in range(max(1, n_workers))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results  # type: ignore


def _mp_board_worker(args):
    base, boards_slice, workers, version, side, chunk = args
    return run_board_batch(base, boards_slice, workers, version=version, side=side, chunk=chunk)


def run_board_batch_mp(base: dict, boards: list[list[int]], n_procs: int, workers_per_proc: int,
                       version: str | None = None, side: str = "p1", chunk: int = 1000) -> list[tuple[int, int]]:
    """Multiprocessing board search: split boards across `n_procs` PYTHON processes (each its own GIL),
    each running run_board_batch with `workers_per_proc` oracle workers. Dodges the single-process GIL
    ceiling (~8 workers saturate one Python process's json+pipe work). Total oracle workers = procs*per.

    Results are bit-exact to the single-process path (same engine, same per-board reset). Returns
    [(hpDelta, turns), ...] aligned to `boards`.
    """
    from concurrent.futures import ProcessPoolExecutor

    n_procs = max(1, n_procs)
    if n_procs == 1:
        return run_board_batch(base, boards, workers_per_proc, version=version, side=side, chunk=chunk)
    # Interleaved slices: board j -> proc j%n_procs, position j//n_procs (cheap to un-interleave).
    args = [(base, boards[i::n_procs], workers_per_proc, version, side, chunk) for i in range(n_procs)]
    out: list[tuple[int, int] | None] = [None] * len(boards)
    with ProcessPoolExecutor(max_workers=n_procs) as ex:
        for pi, rs in enumerate(ex.map(_mp_board_worker, args)):
            for k, val in enumerate(rs):
                out[pi + k * n_procs] = val
    return out  # type: ignore


def _load_sample_fixture() -> dict:
    import glob
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "fixtures", "*.json"))):
        if os.path.basename(f).startswith("_"):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("stat"):
            return d
    sys.exit("no fixture with a `stat` found in data/fixtures/")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", nargs="?", type=int, const=200, default=None, help="run N warm fixtures and time them")
    ap.add_argument("--batch-bench", nargs="?", type=int, const=2000, default=None,
                    help="run N fixtures across a sweep of worker counts and show throughput scaling")
    ap.add_argument("--version", default="001.0007.0000", help="version snapshot to pin the worker to")
    args = ap.parse_args()

    if args.batch_bench is not None:
        fx = _load_sample_fixture()
        fixtures = [fx] * args.batch_bench
        print(f"=== parallel throughput: {args.batch_bench} fixtures, pinned to {args.version} ===")
        for w in (1, 2, 4, 8, 16):
            t0 = time.time()
            res = run_batch(fixtures, n_workers=w, version=args.version)
            dt = time.time() - t0
            ok = sum(1 for r in res if r and r.get("engine") == "oracle")
            print(f"  {w:>2} workers: {dt:6.2f}s  =>  {args.batch_bench/dt:8.0f} fixtures/s  ({ok}/{len(res)} ok)")
        return

    if args.bench is None:
        print("nothing to do; pass --bench [N] or --batch-bench [N]")
        return

    fx = _load_sample_fixture()
    print(f"=== warm-worker benchmark: {args.bench} runs, pinned to {args.version} ===")

    # Cold baseline: one fresh --run-fixture process (DLL-patch + config load + combat).
    import tempfile
    tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(fx, tf); tf.close()
    store = os.path.join(VERSIONS, args.version)
    t0 = time.time()
    subprocess.run([ORACLE_EXE, "--store", store, "--run-fixture", tf.name],
                   capture_output=True, text=True, cwd=os.path.dirname(ORACLE_EXE),
                   env={**os.environ, "ORACLE_MAXDEPTH": "1000"})
    cold = time.time() - t0
    os.unlink(tf.name)

    # Warm: one worker, N fixtures.
    pool = OraclePool()
    t0 = time.time()
    w = pool.worker_for(args.version)
    spawn = time.time() - t0
    first = None
    t0 = time.time()
    for i in range(args.bench):
        r = w.run(fx)
        if i == 0:
            first = r
    warm_total = time.time() - t0
    pool.close()

    per = warm_total / args.bench * 1000
    print(f"  cold single --run-fixture : {cold*1000:7.0f} ms")
    print(f"  warm worker spawn (1x)    : {spawn*1000:7.0f} ms  (one-time)")
    print(f"  warm {args.bench} fixtures      : {warm_total*1000:7.0f} ms  =>  {per:.2f} ms/fixture")
    print(f"  speedup per call          : {cold/(warm_total/args.bench):7.0f}x")
    print(f"  sample result: hpDelta={first.get('hpDelta')} turns={first.get('turns')} "
          f"match={first.get('match')} ok={first.get('ok')}")


if __name__ == "__main__":
    main()
