#!/usr/bin/env python3
"""DEV render smoke test for the battle replay. Loads the harness page in headless Chromium, intercepts
/api/run-replay with a canned payload (so it doesn't need a live oracle), lets battle-assets + /assets/spine proxy
through vite to :8100, screenshots the Spine scene, and reports console errors / failed asset loads + whether the
canvas actually drew non-background pixels.

Prereqs:
  - vite dev server running on :5273  →  (cd web/yisim_ui && npm run dev -- --port 5273)
  - the peer's fixture server on :8100 (serves /api/game/battle-assets + /assets/spine)
  - playwright + a cached chromium  →  uv pip install playwright   (browsers already cached on this box)
Run:  uv run python tools/game-oracle/scripts/render_smoke.py   (exit 0 = RENDER OK)"""
import json, sys, shutil
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
import os
HARNESS = f"{os.environ.get('RENDER_SMOKE_BASE', 'http://127.0.0.1:5273')}/harness.html"
PUBLIC = ROOT / "web" / "yisim_ui" / "public"
CANNED = PUBLIC / "__replay_canned.json"
# Optional CLI arg: a fixture name/path to render (default cfcsuj9-r12). When given, artifacts are regenerated.
_arg = next((a for a in sys.argv[1:] if not a.startswith("-")), None)
FIXTURE_SRC = (ROOT / "data" / "fixtures" / (_arg if _arg and _arg.endswith(".json") else f"{_arg}.json")) if _arg \
    else ROOT / "data" / "fixtures" / "cfcsuj9-r12.json"
FIXTURE_DST = PUBLIC / "__replay_fixture.json"
OUT = ROOT / "web" / "yisim_ui" / "render_smoke.png"


def ensure_artifacts(force: bool = False) -> None:
    """Generate the harness fixture + a canned /api/run-replay payload (so the test needs no live server)."""
    if force or not FIXTURE_DST.exists():
        shutil.copyfile(FIXTURE_SRC, FIXTURE_DST)
    if force or not CANNED.exists():
        sys.path.insert(0, str(ROOT / "tools" / "game-oracle" / "scripts"))
        import replay_routes as R
        res, anim = R.run_oracle_with_anim(FIXTURE_SRC.resolve())
        CANNED.write_text(json.dumps({**res, "anim": anim}, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ensure_artifacts(force=_arg is not None)
    canned = CANNED.read_text(encoding="utf-8")
    console_errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("requestfailed", lambda r: failed.append(f"{r.url} {r.failure}"))
        page.route("**/api/run-replay", lambda route: route.fulfill(status=200, content_type="application/json", body=canned))

        page.goto(HARNESS, wait_until="networkidle", timeout=30000)
        # let assets load + start autoplay
        try:
            page.get_by_role("button", name="Autoplay").click(timeout=8000)
        except Exception as e:
            print(f"[warn] could not click Autoplay: {e}")
        page.wait_for_timeout(3500)
        page.screenshot(path=str(OUT))

        # did the canvas draw anything beyond the flat background?
        nonblank = page.evaluate("""() => {
            const c = document.querySelector('canvas'); if (!c) return {hasCanvas:false};
            const g = document.createElement('canvas'); g.width=c.width; g.height=c.height;
            const ctx = g.getContext('2d'); ctx.drawImage(c,0,0);
            const d = ctx.getImageData(0,0,g.width,g.height).data; const bg=[0x10,0x14,0x1c];
            let diff=0; for(let i=0;i<d.length;i+=4){ if(Math.abs(d[i]-bg[0])+Math.abs(d[i+1]-bg[1])+Math.abs(d[i+2]-bg[2])>24) diff++; }
            return {hasCanvas:true, w:c.width, h:c.height, nonBgPixels:diff, frac:diff/(g.width*g.height)};
        }""")
        browser.close()

    print("canvas:", json.dumps(nonblank))
    spine_reqs = [f for f in failed if ".skel" in f or ".atlas" in f or ".png" in f]
    print(f"console errors: {len(console_errors)}")
    for e in console_errors[:8]:
        print("   ERR", e[:160])
    print(f"failed requests: {len(failed)} (spine asset failures: {len(spine_reqs)})")
    for f in failed[:8]:
        print("   FAIL", f[:160])
    print("screenshot:", OUT)
    ok = nonblank.get("hasCanvas") and nonblank.get("frac", 0) > 0.01 and not spine_reqs
    print("RESULT:", "RENDER OK" if ok else "RENDER PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
