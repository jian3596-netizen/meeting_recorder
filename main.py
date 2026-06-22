"""会议录音机 —— 常驻系统托盘的轻量录音工具。

启动后默认最小化到系统托盘后台运行。
左键单击托盘图标：开始 / 停止录音。
右键菜单：开始/停止、设置（录音源、设备、保存路径）、打开文件夹、退出。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
from pathlib import Path

import pystray
import soundcard as sc
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem as Item

from config import Config
from detector import MeetingDetector
from recorder import AudioRecorder, RecorderError

APP_NAME = "会议录音机"


class TrayApp:
    def __init__(self) -> None:
        self.config = Config.load()
        self.recorder = AudioRecorder(self.config)
        self._auto_started = False     # 本次录音是否由自动探测发起
        self._prompt_open = False      # 是否已有「是否录音」弹窗在显示
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
            Item(
                "■ 停止录音" if recording else "● 开始录音",
                self.on_toggle,
                default=True,  # 左键单击触发
            ),
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
    def on_toggle(self, icon=None, item=None) -> None:
        if self.recorder.is_recording:
            self._stop()
        else:
            self._auto_started = False  # 手动开始的录音不随会议结束自动停止
            self._start()

    def _start(self) -> None:
        try:
            self.recorder.start()
        except RecorderError as exc:
            self._notify("无法开始录音", str(exc))
            return
        self._refresh()
        self._notify(APP_NAME, "录音已开始")

    def _stop(self) -> None:
        path = self.recorder.stop()
        self._refresh()
        if path is not None:
            self._notify("录音已保存", path.name)
        else:
            msg = "；".join(self.recorder.errors) or "未捕获到音频"
            self._notify("录音结束", msg)

    # ---- 自动探测会议 ---------------------------------------------------
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

    def _on_meeting_start(self, label: str) -> None:
        # 已在录音 / 已有弹窗时不再打扰
        if self.recorder.is_recording or self._prompt_open:
            return
        self._prompt_open = True
        threading.Thread(
            target=self._prompt_record, args=(label,), daemon=True
        ).start()

    def _prompt_record(self, label: str) -> None:
        try:
            yes = _ask_yes_no(
                APP_NAME, f"检测到你正在使用「{label}」开会，是否开始录音？"
            )
            if yes and not self.recorder.is_recording:
                self._auto_started = True
                self._start()
        finally:
            self._prompt_open = False

    def _on_meeting_end(self, label: str) -> None:
        # 仅自动开始的录音才随会议结束自动停止保存
        if self._auto_started and self.recorder.is_recording:
            self._auto_started = False
            self._stop()

    # ---- 设置动作 -------------------------------------------------------
    def _toggle_system(self, icon=None, item=None) -> None:
        self.config.record_system = not self.config.record_system
        self.config.save()

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

    def on_open_folder(self, icon=None, item=None) -> None:
        folder = self.config.output_path
        folder.mkdir(parents=True, exist_ok=True)
        _open_in_explorer(folder)

    def on_quit(self, icon=None, item=None) -> None:
        self._stop_detector()
        if self.recorder.is_recording:
            self.recorder.stop()
        self.icon.stop()

    def _notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        if self.config.auto_detect:
            self._start_detector()
        self.icon.run()


def _ask_yes_no(title: str, text: str) -> bool:
    """Windows 原生「是/否」对话框（user32.MessageBox，线程安全）。"""
    if sys.platform != "win32":
        return False
    MB_YESNO = 0x00000004
    MB_ICONQUESTION = 0x00000020
    MB_SETFOREGROUND = 0x00010000
    MB_TOPMOST = 0x00040000
    IDYES = 6
    res = ctypes.windll.user32.MessageBoxW(
        0, text, title, MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND | MB_TOPMOST
    )
    return res == IDYES


def _open_in_explorer(folder: Path) -> None:
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def main() -> None:
    TrayApp().run()


if __name__ == "__main__":
    main()
