#!/usr/bin/env python3
"""
models_routes.py — read-only API over the on-disk training artifacts, for the NN-management dashboard.

Owner: Agent 1 (NN-management UI). Mounted into fixture_editor_server.py by Agent 2 (server owner) via:
    from models_routes import router as models_router; app.include_router(models_router)

Agent 2's trainer/evaluator write these files into data/models/ (NO new training is triggered here — this only
READS what's already on disk):
  - yixian_v<N>.pt                 the trained model checkpoints
  - training_log_v<N>.json         { model, games, total_steps, elapsed_s, device, resumed_from, entries:[
                                     { game, loss, policy_loss, value_loss, steps, avg_steps_per_game, avg_destiny, elapsed_s } ] }
  - eval_yixian_v<N>.pt.json       { model, games, elapsed_s, survival_rate, avg_destiny, avg_steps, ready_per_game,
                                     per_character:{ code:{games, avg_destiny, avg_steps, survival_rate} }, results:[...] }

Endpoints:
  GET /api/models                      -> [{version, file, size, mtime, training:{...summary}, eval:{...summary}}], newest first
  GET /api/models/<version>/training   -> the full training_log (incl. entries for loss curves)
  GET /api/models/<version>/eval       -> the full eval json (incl. per_character)

Standalone test:  uv run python tools/game-oracle/scripts/models_routes.py
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = ROOT / "data" / "models"


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _training_path(version: str) -> Path:
    return MODELS_DIR / f"training_log_{version}.json"


def _eval_path(version: str) -> Path:
    return MODELS_DIR / f"eval_yixian_{version}.pt.json"


def list_models() -> list[dict]:
    """One row per yixian_v<N>.pt, newest first, with compact training + eval summaries (no heavy arrays)."""
    rows = []
    for pt in MODELS_DIR.glob("yixian_v*.pt"):
        m = re.match(r"yixian_(v\d+)\.pt$", pt.name)
        if not m:
            continue
        version = m.group(1)
        st = pt.stat()
        tl = _read_json(_training_path(version)) or {}
        ev = _read_json(_eval_path(version)) or {}
        rows.append({
            "version": version,
            "file": pt.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "training": {k: tl.get(k) for k in ("games", "total_steps", "elapsed_s", "device", "resumed_from")} if tl else None,
            "eval": {k: ev.get(k) for k in ("games", "survival_rate", "avg_destiny", "avg_steps", "ready_per_game", "elapsed_s")} if ev else None,
        })
    rows.sort(key=lambda r: int(r["version"][1:]), reverse=True)
    return rows


def get_training(version: str) -> dict | None:
    return _read_json(_training_path(_norm(version)))


def get_eval(version: str) -> dict | None:
    return _read_json(_eval_path(_norm(version)))


def _norm(version: str) -> str:
    """Accept 'v5', '5', or 'yixian_v5(.pt)' and normalize to 'v5'."""
    m = re.search(r"v?(\d+)", str(version))
    return f"v{m.group(1)}" if m else str(version)


# ── FastAPI router (Agent 2 mounts this) ──────────────────────────────────────────────────────────────
try:
    from fastapi import APIRouter
    from fastapi.responses import JSONResponse
    router = APIRouter()

    @router.get("/api/models")
    def api_models():
        return list_models()

    @router.get("/api/models/{version}/training")
    def api_model_training(version: str):
        data = get_training(version)
        return data if data is not None else JSONResponse(status_code=404, content={"error": f"no training log for {version}"})

    @router.get("/api/models/{version}/eval")
    def api_model_eval(version: str):
        data = get_eval(version)
        return data if data is not None else JSONResponse(status_code=404, content={"error": f"no eval for {version}"})
except ImportError:
    router = None


if __name__ == "__main__":
    models = list_models()
    print(f"{len(models)} models in {MODELS_DIR}:")
    for m in models:
        ev, tl = m["eval"], m["training"]
        line = f"  {m['version']:4} {m['file']:14}"
        if tl: line += f" trained {tl.get('games')}g/{tl.get('total_steps')}steps (from {tl.get('resumed_from')})"
        if ev: line += f" | eval surv {ev.get('survival_rate')} destiny {ev.get('avg_destiny')}"
        print(line)
    if len(sys.argv) > 1:
        v = sys.argv[1]
        ev = get_eval(v) or {}
        print(f"\n{v} per-character eval:")
        for code, s in (ev.get("per_character") or {}).items():
            print(f"  {code:5} destiny {s.get('avg_destiny'):6} surv {s.get('survival_rate')} ({s.get('games')}g)")
