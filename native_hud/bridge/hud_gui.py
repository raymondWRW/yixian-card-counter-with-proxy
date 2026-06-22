# -*- coding: utf-8 -*-
"""Settings window + system-tray for the native HUD.

run_gui(settings, on_exit, status_get): a small always-on-top tkinter panel with
show/hide checkboxes (bound live to `settings`), a solo/matchup radio, a status
line, and an Exit button. Closing the window minimizes to the tray (pystray) if
available; the tray menu can re-show or quit. Exit calls on_exit() (which stops
the HUD and closes the spawned game)."""
import threading
import tkinter as tk
from tkinter import ttk

ELEMENTS = [
    ("remaining", "记牌器 剩X"),
    ("damage", "造伤 T1–T8"),
    ("opponent", "对手 命/修"),
    ("warning", "危险牌警告"),
]


def _make_tray(on_show, on_quit):
    try:
        import pystray
        from PIL import Image, ImageDraw
    except Exception:
        return None
    img = Image.new("RGB", (64, 64), (18, 26, 44))
    d = ImageDraw.Draw(img)
    d.ellipse((12, 12, 52, 52), fill=(120, 200, 255))
    menu = pystray.Menu(
        pystray.MenuItem("显示设置", lambda icon, item: on_show()),
        pystray.MenuItem("退出", lambda icon, item: on_quit()),
    )
    return pystray.Icon("YiXianHUD", img, "弈仙牌 HUD", menu)


def run_gui(settings, on_exit, status_get=None):
    root = tk.Tk()
    root.title("弈仙牌 HUD")
    root.geometry("260x340")
    root.attributes("-topmost", True)
    frm = ttk.Frame(root, padding=12)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="显示元素", font=("", 10, "bold")).pack(anchor="w")
    for key, text in ELEMENTS:
        var = tk.BooleanVar(value=bool(settings.get(key, True)))

        def _bind(k=key, v=var):
            settings[k] = bool(v.get())
        ttk.Checkbutton(frm, text=text, variable=var, command=_bind).pack(anchor="w")

    ttk.Separator(frm).pack(fill="x", pady=8)
    ttk.Label(frm, text="伤害模式", font=("", 10, "bold")).pack(anchor="w")
    mode = tk.StringVar(value="matchup" if settings.get("matchup", True) else "solo")

    def _mode():
        settings["matchup"] = (mode.get() == "matchup")
    ttk.Radiobutton(frm, text="对打对手 (matchup)", variable=mode,
                    value="matchup", command=_mode).pack(anchor="w")
    ttk.Radiobutton(frm, text="自身输出 (solo)", variable=mode,
                    value="solo", command=_mode).pack(anchor="w")

    ttk.Separator(frm).pack(fill="x", pady=8)
    status = ttk.Label(frm, text="启动中…", foreground="gray", wraplength=230)
    status.pack(anchor="w")

    tray = {"icon": None}

    def _quit():
        if tray["icon"] is not None:
            try:
                tray["icon"].stop()
            except Exception:
                pass
        try:
            on_exit()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass

    ttk.Button(frm, text="退出 (关HUD+游戏)", command=_quit).pack(side="bottom", fill="x", pady=(8, 0))

    # Close button → minimize to tray (don't quit) if a tray icon exists.
    def _on_close():
        if tray["icon"] is not None:
            root.withdraw()
        else:
            _quit()
    root.protocol("WM_DELETE_WINDOW", _on_close)

    icon = _make_tray(on_show=lambda: root.after(0, root.deiconify),
                      on_quit=lambda: root.after(0, _quit))
    if icon is not None:
        tray["icon"] = icon
        threading.Thread(target=icon.run, daemon=True).start()

    if status_get:
        def _tick():
            try:
                status.config(text=status_get())
            except Exception:
                pass
            root.after(1000, _tick)
        _tick()

    root.mainloop()
