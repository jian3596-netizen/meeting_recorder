"""会议自动探测。

原理：Windows 在注册表 CapabilityAccessManager\\ConsentStore\\microphone 下
为每个使用过麦克风的应用记录 LastUsedTimeStop —— 当应用**正在**占用麦克风时
该值为 0，停止后写入时间戳。据此判断 Teams / 腾讯会议是否正在开会。
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("detector")

try:
    import winreg
except ImportError:  # 非 Windows 平台
    winreg = None  # type: ignore[assignment]

_CONSENT_BASE = (
    r"Software\Microsoft\Windows\CurrentVersion"
    r"\CapabilityAccessManager\ConsentStore\microphone"
)

# 子键名（应用包名或可执行文件路径）里包含这些片段即视为目标会议软件
_TARGETS: dict[str, str] = {
    "msteams": "Microsoft Teams",
    "teams.exe": "Microsoft Teams",
    "wemeet": "腾讯会议",
    "wemeetapp": "腾讯会议",
}


def _match_label(subkey_name: str) -> str | None:
    low = subkey_name.lower()
    for needle, label in _TARGETS.items():
        if needle in low:
            return label
    return None


def active_meeting_apps() -> set[str]:
    """返回当前正在占用麦克风的目标会议软件标签集合。"""
    if winreg is None:
        return set()

    active: set[str] = set()
    for suffix in ("", r"\NonPackaged"):
        path = _CONSENT_BASE + suffix
        try:
            root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                label = _match_label(name)
                if not label:
                    continue
                try:
                    with winreg.OpenKey(root, name) as sub:
                        stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                    if stop == 0:  # 0 = 正在使用麦克风
                        active.add(label)
                except OSError:
                    continue
        finally:
            winreg.CloseKey(root)
    return active


class MeetingDetector(threading.Thread):
    """后台轮询，检测会议软件开始/结束占用麦克风。"""

    def __init__(
        self,
        on_start: Callable[[str], None],
        on_stop: Callable[[str], None],
        interval: float = 3.0,
    ) -> None:
        super().__init__(daemon=True)
        self.on_start = on_start
        self.on_stop = on_stop
        self.interval = interval
        self._stop_event = threading.Event()
        self._active: set[str] = set()
        self._primed = False

    def run(self) -> None:
        # 首次轮询只记录现状、不触发回调，避免启动瞬间为「已在进行的通话」弹窗
        try:
            self._active = active_meeting_apps()
        except Exception:  # noqa: BLE001
            self._active = set()
        self._primed = True

        while not self._stop_event.wait(self.interval):
            try:
                current = active_meeting_apps()
            except Exception:  # noqa: BLE001
                continue
            for label in current - self._active:
                self._safe(self.on_start, label)
            for label in self._active - current:
                self._safe(self.on_stop, label)
            self._active = current

    @staticmethod
    def _safe(fn: Callable[[str], None], label: str) -> None:
        try:
            fn(label)
        except Exception:  # noqa: BLE001  回调异常不应中断探测循环
            log.exception("会议探测回调出错")

    def stop(self) -> None:
        self._stop_event.set()
