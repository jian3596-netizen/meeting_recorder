"""右下角气泡提示（浅色半透明圆角，可带按钮）。

- `show_toast` 自绘一个无边框、置顶的小卡片，定位在屏幕工作区右下角。
- `ToastManager` 用单独一个线程串行显示所有气泡，避免多线程同时操作
  tkinter；询问类气泡可阻塞等待用户选择，状态类气泡即发即忘。
"""

from __future__ import annotations

import queue
import sys
import threading
from typing import Any

_BG = "#f6f7f9"          # 浅色背景
_FG = "#1b1b1d"          # 主文字
_SUB = "#5f6368"         # 次要文字
_ACCENT = "#e62828"      # 强调按钮（如「开始录音」）
_ACCENT_FG = "#ffffff"
_NORMAL_BG = "#e4e6ea"   # 普通按钮
_NORMAL_FG = "#3a3c40"
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
    """用圆角矩形区域裁剪窗口（Windows）。"""
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


def show_toast(
    title: str,
    message: str,
    buttons: list[tuple[str, Any, str]],
    timeout_sec: int = 20,
    default: Any = None,
) -> Any:
    """显示一个气泡卡片，返回被点击按钮的值；超时返回 default。

    buttons：[(文字, 返回值, 样式)]，样式为 "accent" 或 "normal"。
    按列表顺序从右往左排列（第一个在最右，作为主按钮）。
    """
    try:
        import tkinter as tk
    except Exception:  # noqa: BLE001
        return default

    result = {"value": default}

    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", _ALPHA)
    except Exception:  # noqa: BLE001
        pass

    frame = tk.Frame(root, bg=_BG, highlightbackground=_BORDER, highlightthickness=1)
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame, text=title, bg=_BG, fg=_FG,
        font=(_FONT, 11, "bold"), anchor="w",
    ).pack(fill="x", padx=16, pady=(13, 2))

    tk.Label(
        frame, text=message, bg=_BG, fg=_SUB,
        font=(_FONT, 9), anchor="w", justify="left", wraplength=300,
    ).pack(fill="x", padx=16, pady=(0, 14 if not buttons else 12))

    def choose(value: Any) -> None:
        result["value"] = value
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    if buttons:
        btns = tk.Frame(frame, bg=_BG)
        btns.pack(fill="x", padx=16, pady=(0, 14))
        for text, value, style in buttons:
            accent = style == "accent"
            fg = _ACCENT_FG if accent else _NORMAL_FG
            bg = _ACCENT if accent else _NORMAL_BG
            tk.Button(
                btns, text=text, command=lambda v=value: choose(v),
                fg=fg, bg=bg, activebackground=bg, activeforeground=fg,
                relief="flat", bd=0, padx=16, pady=6,
                font=(_FONT, 9, "bold"), cursor="hand2",
            ).pack(side="right", padx=(8, 0))

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
    root.after(max(1, timeout_sec) * 1000, lambda: choose(default))
    root.mainloop()
    return result["value"]


class _Request:
    def __init__(self, title, message, buttons, timeout, default) -> None:
        self.title = title
        self.message = message
        self.buttons = buttons
        self.timeout = timeout
        self.default = default
        self.result: Any = default
        self.done = threading.Event()


class ToastManager:
    """单线程串行显示所有气泡。"""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            req = self._q.get()
            if req is None:
                break
            try:
                req.result = show_toast(
                    req.title, req.message, req.buttons, req.timeout, req.default
                )
            except Exception:  # noqa: BLE001
                req.result = req.default
            finally:
                req.done.set()

    def ask(
        self,
        title: str,
        message: str,
        buttons: list[tuple[str, Any, str]],
        default: Any = None,
        timeout: int = 20,
    ) -> Any:
        """显示询问气泡并阻塞等待用户选择。"""
        req = _Request(title, message, buttons, timeout, default)
        self._q.put(req)
        req.done.wait()
        return req.result

    def info(self, title: str, message: str, timeout: int = 2) -> None:
        """显示状态气泡（无按钮，2 秒后自动消失）。"""
        req = _Request(title, message, [], timeout, True)
        self._q.put(req)

    def stop(self) -> None:
        self._q.put(None)
