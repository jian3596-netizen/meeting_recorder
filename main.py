"""会议录音机 —— 常驻系统托盘的轻量录音工具。

启动后默认最小化到系统托盘后台运行。
左键双击托盘图标：开始 / 停止录音。
右键菜单：开始/停止、设置（录音源、设备）、打开文件夹、退出。
"""

from __future__ import annotations

import functools
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pystray
import soundcard as sc
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem as Item

import applog
import toast
from config import Config
from detector import MeetingDetector
from recorder import AudioRecorder, RecorderError

log = logging.getLogger("main")

APP_NAME = "会议录音机"
MAX_DURATION_SEC = 2 * 60 * 60     # 录音最大时长 2 小时
WARN_BEFORE_SEC = 10 * 60          # 距上限 10 分钟时提示


def _safe_action(fn):
    """包裹托盘回调 / 后台动作：出错记日志，避免异常搞挂 pystray 消息循环。"""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("操作出错：%s", fn.__name__)
            try:
                self._notify("出错了", f"{fn.__name__} 执行失败，详见 error.log")
            except Exception:  # noqa: BLE001
                pass

    return wrapper


class TrayApp:
    def __init__(self) -> None:
        self.config = Config.load()
        self.recorder = AudioRecorder(self.config)
        self.toasts = toast.ToastManager()
        self._prompt_open = False      # 是否已有「是否录音」气泡在显示
        self._last_click: float | None = None  # 上次托盘左键点击时间（识别双击）
        self._dbl_threshold = _double_click_seconds()
        self._warn_timer: threading.Timer | None = None
        self._max_timer: threading.Timer | None = None
        self.detector: MeetingDetector | None = None
        self.icon = pystray.Icon(
            "meeting_recorder",
            icon=self._make_icon(recording=False),
            title=APP_NAME,
            menu=self._build_menu(),
        )

    # ---- 图标 -----------------------------------------------------------
    def _make_icon(self, recording: bool) -> Image.Image:
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((4, 4, size - 4, size - 4), fill=(40, 40, 40, 255))
        color = (230, 40, 40, 255) if recording else (160, 160, 160, 255)
        draw.ellipse((20, 20, size - 20, size - 20), fill=color)
        return img

    def _refresh(self) -> None:
        rec = self.recorder.is_recording
        self.icon.icon = self._make_icon(recording=rec)
        self.icon.title = f"{APP_NAME} — {'录音中…' if rec else '空闲'}"
        self.icon.menu = self._build_menu()
        self.icon.update_menu()

    # ---- 菜单 -----------------------------------------------------------
    def _build_menu(self) -> Menu:
        recording = self.recorder.is_recording
        return Menu(
            # 菜单里的项：单击即切换（这是用户主动点菜单）
            Item(
                "停止录音" if recording else "开始录音",
                self._menu_toggle,
            ),
            # 隐藏的默认项：响应托盘图标左键点击，用于识别「双击」
            Item("", self._on_icon_click, default=True, visible=False),
            Menu.SEPARATOR,
            Item("设置", self._settings_menu()),
            Item("打开录音文件夹", self.on_open_folder),
            Menu.SEPARATOR,
            Item("退出", self.on_quit),
        )

    def _settings_menu(self) -> Menu:
        return Menu(
            Item(
                "自动探测会议（Teams / 腾讯会议）",
                self._toggle_auto_detect,
                checked=lambda _i: self.config.auto_detect,
            ),
            Menu.SEPARATOR,
            Item(
                "录音源 → 系统音频",
                self._toggle_system,
                checked=lambda _i: self.config.record_system,
            ),
            Item(
                "录音源 → 麦克风",
                self._toggle_mic,
                checked=lambda _i: self.config.record_mic,
            ),
            Menu.SEPARATOR,
            Item("扬声器设备", self._speaker_menu()),
            Item("麦克风设备", self._mic_menu()),
        )

    def _speaker_menu(self) -> Menu:
        items = [
            Item(
                "系统默认",
                self._select_speaker(""),
                checked=lambda _i: not self.config.speaker_name,
                radio=True,
            )
        ]
        try:
            speakers = sc.all_speakers()
        except Exception:  # noqa: BLE001
            speakers = []
        for spk in speakers:
            name = str(spk.name)
            items.append(
                Item(
                    name,
                    self._select_speaker(name),
                    checked=lambda _i, n=name: self.config.speaker_name == n,
                    radio=True,
                )
            )
        return Menu(*items)

    def _mic_menu(self) -> Menu:
        items = [
            Item(
                "系统默认",
                self._select_mic(""),
                checked=lambda _i: not self.config.mic_name,
                radio=True,
            )
        ]
        try:
            mics = sc.all_microphones(include_loopback=False)
        except Exception:  # noqa: BLE001
            mics = []
        for mic in mics:
            name = str(mic.name)
            items.append(
                Item(
                    name,
                    self._select_mic(name),
                    checked=lambda _i, n=name: self.config.mic_name == n,
                    radio=True,
                )
            )
        return Menu(*items)

    # ---- 录音动作 -------------------------------------------------------
    def _do_toggle(self) -> None:
        if self.recorder.is_recording:
            self._stop()
        else:
            self._start()

    @_safe_action
    def _menu_toggle(self, icon=None, item=None) -> None:
        # 从右键菜单点击：单击即切换
        self._do_toggle()

    @_safe_action
    def _on_icon_click(self, icon=None, item=None) -> None:
        # 托盘图标左键：双击才切换（两次点击间隔在系统双击时间内）
        now = time.monotonic()
        if self._last_click is not None and now - self._last_click <= self._dbl_threshold:
            self._last_click = None
            self._do_toggle()
        else:
            self._last_click = now

    def _start(self) -> None:
        try:
            self.recorder.start()
        except RecorderError as exc:
            self._notify("无法开始录音", str(exc))
            return
        self._refresh()
        self._start_duration_timers()
        self._notify("录音已开始", "正在录制系统音频 + 麦克风")

    def _stop(self, reason: str | None = None) -> None:
        self._cancel_duration_timers()
        path = self.recorder.stop()
        self._refresh()
        if path is not None:
            self._notify(reason or "录音已保存", path.name)
        else:
            msg = "；".join(self.recorder.errors) or "未捕获到音频"
            self._notify("录音结束", msg)

    # ---- 最大时长控制 ---------------------------------------------------
    def _start_duration_timers(self) -> None:
        self._cancel_duration_timers()
        warn_after = max(1, MAX_DURATION_SEC - WARN_BEFORE_SEC)
        self._warn_timer = threading.Timer(warn_after, self._on_duration_warning)
        self._max_timer = threading.Timer(MAX_DURATION_SEC, self._on_duration_max)
        for t in (self._warn_timer, self._max_timer):
            t.daemon = True
            t.start()

    def _cancel_duration_timers(self) -> None:
        for t in (self._warn_timer, self._max_timer):
            if t is not None:
                t.cancel()
        self._warn_timer = self._max_timer = None

    @_safe_action
    def _on_duration_warning(self) -> None:
        if not self.recorder.is_recording:
            return
        stop = self.toasts.ask(
            "录音即将达到 2 小时上限",
            "还剩约 10 分钟，是否现在停止并保存？",
            [("现在停止", True, "accent"), ("继续录制", False, "normal")],
            default=False,
        )
        if stop and self.recorder.is_recording:
            self._stop()

    @_safe_action
    def _on_duration_max(self) -> None:
        if self.recorder.is_recording:
            self._stop(reason="已达 2 小时上限，录音已自动保存")

    # ---- 自动探测会议 ---------------------------------------------------
    @_safe_action
    def _toggle_auto_detect(self, icon=None, item=None) -> None:
        self.config.auto_detect = not self.config.auto_detect
        self.config.save()
        if self.config.auto_detect:
            self._start_detector()
        else:
            self._stop_detector()

    def _start_detector(self) -> None:
        if self.detector is not None:
            return
        self.detector = MeetingDetector(
            on_start=self._on_meeting_start,
            on_stop=self._on_meeting_end,
        )
        self.detector.start()

    def _stop_detector(self) -> None:
        if self.detector is not None:
            self.detector.stop()
            self.detector = None

    @_safe_action
    def _on_meeting_start(self, label: str) -> None:
        # 已在录音 / 已有弹窗时不再打扰
        if self.recorder.is_recording or self._prompt_open:
            return
        self._prompt_open = True
        threading.Thread(
            target=self._prompt_start, args=(label,), daemon=True
        ).start()

    @_safe_action
    def _prompt_start(self, label: str) -> None:
        try:
            yes = self.toasts.ask(
                f"检测到「{label}」会议",
                "是否开始录音？",
                [("开始录音", True, "accent"), ("忽略", False, "normal")],
                default=False,
            )
            if yes and not self.recorder.is_recording:
                self._start()
        finally:
            self._prompt_open = False

    @_safe_action
    def _on_meeting_end(self, label: str) -> None:
        # 会议结束（会议软件停止占用麦克风）：若在录音则询问是否停止
        if not self.recorder.is_recording:
            return
        threading.Thread(
            target=self._prompt_end, args=(label,), daemon=True
        ).start()

    @_safe_action
    def _prompt_end(self, label: str) -> None:
        stop = self.toasts.ask(
            f"「{label}」会议已结束",
            "是否停止录音？",
            [("停止录音", True, "accent"), ("继续录音", False, "normal")],
            default=False,
        )
        if stop and self.recorder.is_recording:
            self._stop()

    # ---- 设置动作 -------------------------------------------------------
    @_safe_action
    def _toggle_system(self, icon=None, item=None) -> None:
        self.config.record_system = not self.config.record_system
        self.config.save()

    @_safe_action
    def _toggle_mic(self, icon=None, item=None) -> None:
        self.config.record_mic = not self.config.record_mic
        self.config.save()

    def _select_speaker(self, name: str):
        def handler(icon=None, item=None) -> None:
            self.config.speaker_name = name
            self.config.save()
        return handler

    def _select_mic(self, name: str):
        def handler(icon=None, item=None) -> None:
            self.config.mic_name = name
            self.config.save()
        return handler

    @_safe_action
    def on_open_folder(self, icon=None, item=None) -> None:
        folder = self.config.output_path
        folder.mkdir(parents=True, exist_ok=True)
        _open_in_explorer(folder)

    @_safe_action
    def on_quit(self, icon=None, item=None) -> None:
        self._stop_detector()
        self._cancel_duration_timers()
        if self.recorder.is_recording:
            self.recorder.stop()
        self.toasts.stop()
        self.icon.stop()

    def _notify(self, title: str, message: str) -> None:
        # 状态提示统一用气泡卡片样式
        self.toasts.info(title, message)

    def run(self) -> None:
        if self.config.auto_detect:
            self._start_detector()
        self.icon.run()


def _double_click_seconds() -> float:
    """系统双击判定时间（秒）；非 Windows 或获取失败时回退 0.5s。"""
    if sys.platform == "win32":
        try:
            import ctypes

            ms = ctypes.windll.user32.GetDoubleClickTime()
            if ms:
                return ms / 1000.0
        except Exception:  # noqa: BLE001
            pass
    return 0.5


def _open_in_explorer(folder: Path) -> None:
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def main() -> None:
    applog.setup()
    try:
        TrayApp().run()
    except Exception:  # noqa: BLE001
        log.exception("程序异常退出")
        raise


if __name__ == "__main__":
    main()
