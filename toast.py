"""右下角气泡提示（带按钮），用于「检测到会议，是否录音」。

用 tkinter 自绘一个无边框、置顶、浅色半透明、圆角的小卡片，
定位在屏幕工作区右下角。必须在独立线程中调用（自带事件循环，
阻塞至用户选择或超时）。
"""

from __future__ import annotations

import sys

_BG = "#f6f7f9"          # 浅色背景
_FG = "#1b1b1d"          # 主文字
_SUB = "#5f6368"         # 次要文字
_ACCENT = "#e62828"      # 「开始录音」按钮
_IGNORE_BG = "#e4e6ea"   # 「忽略」按钮
_IGNORE_FG = "#3a3c40"
_BORDER = "#d4d6da"
_FONT = "Microsoft YaHei UI"
_MARGIN = 16
_RADIUS = 18
_ALPHA = 0.94


def _work_area() -> tuple[int, int, int, int]:
    """返回屏幕工作区 (left, top, right, bottom)，已排除任务栏。"""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            SPI_GETWORKAREA = 0x0030
            rect = wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(
                SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
            )
            return rect.left, rect.top, rect.right, rect.bottom
        except Exception:  # noqa: BLE001
            pass
    return 0, 0, 0, 0


def _round_corners(root, w: int, h: int) -> None:
    """用圆角矩形区域裁剪窗口，得到圆角效果（Windows）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        GA_ROOT = 2
        hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), GA_ROOT)
        region = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, w + 1, h + 1, _RADIUS, _RADIUS
        )
        ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    except Exception:  # noqa: BLE001
        pass


def ask_record(title: str, message: str, timeout_sec: int = 20) -> bool:
    """显示右下角气泡，返回 True 表示用户选择「开始录音」。"""
    try:
        import tkinter as tk
    except Exception:  # noqa: BLE001
        return False

    result = {"yes": False}

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", _ALPHA)
    except Exception:  # noqa: BLE001
        pass

    frame = tk.Frame(
        root, bg=_BG, highlightbackground=_BORDER, highlightthickness=1
    )
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame, text=title, bg=_BG, fg=_FG,
        font=(_FONT, 11, "bold"), anchor="w",
    ).pack(fill="x", padx=16, pady=(13, 2))

    tk.Label(
        frame, text=message, bg=_BG, fg=_SUB,
        font=(_FONT, 9), anchor="w", justify="left", wraplength=300,
    ).pack(fill="x", padx=16, pady=(0, 12))

    btns = tk.Frame(frame, bg=_BG)
    btns.pack(fill="x", padx=16, pady=(0, 14))

    def choose(yes: bool) -> None:
        result["yes"] = yes
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def make_btn(text: str, fg: str, bg: str, yes: bool) -> tk.Button:
        return tk.Button(
            btns, text=text, command=lambda: choose(yes),
            fg=fg, bg=bg, activebackground=bg, activeforeground=fg,
            relief="flat", bd=0, padx=16, pady=6,
            font=(_FONT, 9, "bold"), cursor="hand2",
        )

    make_btn("开始录音", "#ffffff", _ACCENT, True).pack(side="right", padx=(8, 0))
    make_btn("忽略", _IGNORE_FG, _IGNORE_BG, False).pack(side="right")

    # 定位到工作区右下角
    root.update_idletasks()
    w = max(330, frame.winfo_reqwidth())
    h = frame.winfo_reqheight()
    left, top, right, bottom = _work_area()
    if right and bottom:
        x = right - w - _MARGIN
        y = bottom - h - _MARGIN
    else:
        x = root.winfo_screenwidth() - w - _MARGIN
        y = root.winfo_screenheight() - h - 60
    root.geometry(f"{w}x{h}+{x}+{y}")

    root.deiconify()
    root.update_idletasks()
    _round_corners(root, w, h)
    root.lift()
    root.attributes("-topmost", True)
    root.after(max(1, timeout_sec) * 1000, lambda: choose(False))
    root.mainloop()
    return result["yes"]
