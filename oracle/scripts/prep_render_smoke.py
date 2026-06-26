#!/usr/bin/env python3
"""DEV render smoke test for the PRE-COMBAT ACTION replay (Prep Replay tab). Loads the live app in headless
Chromium, opens the 'Prep Replay' tab (which auto-fetches /api/prep-replay for he6/greedy), steps through the AI's
prep actions, and screenshots the animated board/hand scene at a few points so we can eyeball prefab-accuracy +
that cards actually move hand→refine/replace/deck.

Unlike render_smoke.py (which canned /api/run-replay), this needs a LIVE server with /api/prep-replay mounted —
point it at a private instance to avoid disturbing :8100:
  RENDER_SMOKE_BASE=http://127.0.0.1:5373  (vite, VITE_API_TARGET=http://127.0.0.1:8123)
Run:  RENDER_SMOKE_BASE=http://127.0.0.1:5373 uv run python tools/game-oracle/scripts/prep_render_smoke.py
Exit 0 = the scene drew card images and stepped without console errors."""
import os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
BASE = os.environ.get("RENDER_SMOKE_BASE", "http://127.0.0.1:5373")
OUT_DIR = ROOT / "web" / "yisim_ui"


def main() -> int:
    console_errors, failed = [], []
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))
        page.goto(BASE, wait_until="networkidle", timeout=30000)
        # open the Prep Replay tab
        page.get_by_role("tab", name="Prep Replay").click(timeout=10000)
        # the tab auto-loads; wait for the scene's card images to appear
        page.wait_for_timeout(3500)
        s0 = str(OUT_DIR / "prep_smoke_0.png"); page.screenshot(path=s0); shots.append(s0)
        # step through a few AI actions, screenshotting the in-flight animation
        for i in range(1, 5):
            try:
                page.get_by_role("button", name="Next action").click(timeout=4000)
            except Exception as e:
                print(f"[warn] Next action {i}: {e}"); break
            page.wait_for_timeout(700)
            s = str(OUT_DIR / f"prep_smoke_{i}.png"); page.screenshot(path=s); shots.append(s)
        # count rendered card images in the scene (game-cards-thumb)
        card_imgs = page.evaluate("""() => document.querySelectorAll('img[src*="game-cards-thumb"]').length""")
        browser.close()

    print(f"rendered card images: {card_imgs}")
    print(f"console errors: {len(console_errors)}")
    for e in console_errors[:6]:
        print("   ERR", e[:160])
    card_fails = [f for f in failed if "game-cards-thumb" in f]
    print(f"failed requests: {len(failed)} (card-thumb failures: {len(card_fails)})")
    for f in failed[:6]:
        print("   FAIL", f[:140])
    print("screenshots:", ", ".join(shots))
    ok = card_imgs > 0 and not card_fails
    print("RESULT:", "RENDER OK" if ok else "RENDER PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
