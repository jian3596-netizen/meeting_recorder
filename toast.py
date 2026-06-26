"""右下角气泡提示（浅色半透明圆角，可带按钮）。

关键：tkinter 不能跨线程使用，也经不起反复 `Tk()` 创建/销毁。本模块用
**一个常驻的 Tk 根窗口**跑在单独一个线程里，所有气泡都作为 `Toplevel`
通过 `after()` 在该线程内创建/销毁；其它线程只通过线程安全的队列与
`Event` 通信，绝不直接碰 tkinter。这样既保证线程安全，又避免长时间运行后
因反复创建根窗口而卡死。
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from typing import Any

log = logging.getLogger("toast")

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
_POLL_MS = 100           # 轮询队列间隔
_MAX_PENDING = 6         # 状态气泡积压上限，超过则丢弃新的状态气泡


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


def _round_corners(win, w: int, h: int) -> None:
    """用圆角矩形区域裁剪窗口（Windows）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        GA_ROOT = 2
        hwnd = ctypes.windll.user32.GetAncestor(win.winfo_id(), GA_ROOT)
        region = ctypes.windll.gdi32.CreateRoundRectRgn(
            0, 0, w + 1, h + 1, _RADIUS, _RADIUS
        )
        ctypes.windll.user32.SetWindowRgn(hwnd, region, True)
    except Exception:  # noqa: BLE001
        pass


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
    """常驻 Tk 根窗口 + 队列，串行显示所有气泡。"""

    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._disabled = False
        self._root = None
        self._tk = None
        self._current = None  # 当前正在显示的 Toplevel
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ToastGUI"
        )
        self._thread.start()

    # ---- GUI 线程 -------------------------------------------------------
    def _run(self) -> None:
        try:
            import tkinter as tk
        except Exception:  # noqa: BLE001
            log.exception("tkinter 不可用，气泡功能禁用")
            self._disabled = True
            self._ready.set()
            return
        try:
            self._tk = tk
            self._root = tk.Tk()
            self._root.withdraw()
            self._ready.set()
            self._root.after(_POLL_MS, self._poll)
            self._root.mainloop()
        except Exception:  # noqa: BLE001
            log.exception("气泡 GUI 线程异常退出")
            self._disabled = True
            self._ready.set()

    def _poll(self) -> None:
        # 有气泡在显示则等它关闭
        if self._current is not None:
            self._root.after(_POLL_MS, self._poll)
            return
        try:
            req = self._q.get_nowait()
        except queue.Empty:
            self._root.after(_POLL_MS, self._poll)
            return

        if req is None:  # 退出信号
            try:
                self._root.quit()
            except Exception:  # noqa: BLE001
                pass
            return

        try:
            self._show(req)
        except Exception:  # noqa: BLE001
            log.exception("显示气泡出错")
            self._current = None
            req.result = req.default
            req.done.set()
            self._root.after(_POLL_MS, self._poll)

    def _show(self, req: _Request) -> None:
        tk = self._tk
        top = tk.Toplevel(self._root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", _ALPHA)
        except Exception:  # noqa: BLE001
            pass

        frame = tk.Frame(
            top, bg=_BG, highlightbackground=_BORDER, highlightthickness=1
        )
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame, text=req.title, bg=_BG, fg=_FG,
            font=(_FONT, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=16, pady=(13, 2))

        tk.Label(
            frame, text=req.message, bg=_BG, fg=_SUB,
            font=(_FONT, 9), anchor="w", justify="left", wraplength=300,
        ).pack(fill="x", padx=16, pady=(0, 14 if not req.buttons else 12))

        closed = {"v": False}

        def close(value: Any) -> None:
            if closed["v"]:
                return
            closed["v"] = True
            req.result = value
            req.done.set()
            try:
                top.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._current = None
            self._root.after(_POLL_MS, self._poll)

        if req.buttons:
            btns = tk.Frame(frame, bg=_BG)
            btns.pack(fill="x", padx=16, pady=(0, 14))
            for text, value, style in req.buttons:
                accent = style == "accent"
                fg = _ACCENT_FG if accent else _NORMAL_FG
                bg = _ACCENT if accent else _NORMAL_BG
                tk.Button(
                    btns, text=text, command=lambda v=value: close(v),
                    fg=fg, bg=bg, activebackground=bg, activeforeground=fg,
                    relief="flat", bd=0, padx=16, pady=6,
                    font=(_FONT, 9, "bold"), cursor="hand2",
                ).pack(side="right", padx=(8, 0))

        top.update_idletasks()
        w = max(330, frame.winfo_reqwidth())
        h = frame.winfo_reqheight()
        left, t, right, bottom = _work_area()
        if right and bottom:
            x = right - w - _MARGIN
            y = bottom - h - _MARGIN
        else:
            x = top.winfo_screenwidth() - w - _MARGIN
            y = top.winfo_screenheight() - h - 60
        top.geometry(f"{w}x{h}+{x}+{y}")

        top.deiconify()
        top.update_idletasks()
        _round_corners(top, w, h)
        top.lift()
        top.attributes("-topmost", True)
        top.after(max(1, req.timeout) * 1000, lambda: close(req.default))
        self._current = top

    # ---- 对外接口（其它线程调用）---------------------------------------
    def ask(
        self,
        title: str,
        message: str,
        buttons: list[tuple[str, Any, str]],
        default: Any = None,
        timeout: int = 20,
    ) -> Any:
        """显示询问气泡并阻塞等待用户选择；GUI 不可用或超时返回 default。"""
        if not self._ready.wait(timeout=5) or self._disabled:
            return default
        req = _Request(title, message, buttons, timeout, default)
        self._q.put(req)
        # 硬超时兜底：即使 GUI 线程异常也不会让调用线程永久阻塞（防线程泄漏）
        if not req.done.wait(timeout=timeout + 15):
            log.warning("气泡等待超时，返回默认值：%s", title)
            return req.default
        return req.result

    def info(self, title: str, message: str, timeout: int = 2) -> None:
        """显示状态气泡（无按钮，自动消失，即发即忘）。"""
        if self._disabled:
            return
        if self._q.qsize() >= _MAX_PENDING:  # 防止状态气泡积压
            return
        req = _Request(title, message, [], timeout, True)
        self._q.put(req)

    def stop(self) -> None:
        self._q.put(None)
