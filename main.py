"""会议录音机 —— 常驻系统托盘的轻量录音工具。

启动后默认最小化到系统托盘后台运行。
左键单击托盘图标：开始 / 停止录音。
右键菜单：开始/停止、设置（录音源、设备、保存路径）、打开文件夹、退出。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pystray
import soundcard as sc
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem as Item

from config import Config
from recorder import AudioRecorder, RecorderError

APP_NAME = "会议录音机"


class TrayApp:
    def __init__(self) -> None:
        self.config = Config.load()
        self.recorder = AudioRecorder(self.config)
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
            Menu.SEPARATOR,
            Item(
                lambda _i: f"保存路径：{self.config.output_dir}",
                self.on_choose_folder,
            ),
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

    def on_choose_folder(self, icon=None, item=None) -> None:
        chosen = _ask_directory(self.config.output_dir)
        if chosen:
            self.config.output_dir = chosen
            self.config.save()
            self.icon.update_menu()
            self._notify("保存路径已更新", chosen)

    def on_open_folder(self, icon=None, item=None) -> None:
        folder = self.config.output_path
        folder.mkdir(parents=True, exist_ok=True)
        _open_in_explorer(folder)

    def on_quit(self, icon=None, item=None) -> None:
        if self.recorder.is_recording:
            self.recorder.stop()
        self.icon.stop()

    def _notify(self, title: str, message: str) -> None:
        try:
            self.icon.notify(message, title)
        except Exception:  # noqa: BLE001
            pass

    def run(self) -> None:
        self.icon.run()


def _ask_directory(initial: str) -> str | None:
    """弹出文件夹选择对话框。

    pystray 在 Windows 上从子线程调用菜单回调，而 tkinter 必须运行在主线程，
    在子线程弹 tkinter 对话框会死锁。因此 Windows 下改用原生 shell 对话框
    （ctypes 调用 shell32，可在任意线程安全使用）。
    """
    if sys.platform == "win32":
        return _ask_directory_win()
    return _ask_directory_tk(initial)


def _ask_directory_win() -> str | None:
    """Windows 原生「浏览文件夹」对话框（SHBrowseForFolder）。"""
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    BIF_RETURNONLYFSDIRS = 0x00000001
    BIF_NEWDIALOGSTYLE = 0x00000040

    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]

    # NEWDIALOGSTYLE 需要 STA 的 COM 单元
    ole32.CoInitialize(None)
    try:
        display = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFO()
        bi.hwndOwner = None
        bi.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
        bi.lpszTitle = "选择录音保存文件夹"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None
        try:
            path_buf = ctypes.create_unicode_buffer(260)
            if shell32.SHGetPathFromIDListW(pidl, path_buf):
                return path_buf.value or None
        finally:
            ole32.CoTaskMemFree(pidl)
        return None
    finally:
        ole32.CoUninitialize()


def _ask_directory_tk(initial: str) -> str | None:
    """非 Windows 平台的后备：tkinter 文件夹对话框。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:  # noqa: BLE001
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        chosen = filedialog.askdirectory(initialdir=initial or os.getcwd())
    finally:
        root.destroy()
    return chosen or None


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
