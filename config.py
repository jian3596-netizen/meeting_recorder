"""应用配置：持久化到 JSON 文件。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def config_dir() -> Path:
    """配置文件所在目录（Windows: %APPDATA%\\MeetingRecorder）。"""
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home()
    return root / "MeetingRecorder"


def default_output_dir() -> Path:
    """默认录音保存目录：用户主目录下的 Meeting Recordings。"""
    return Path.home() / "Meeting Recordings"


CONFIG_PATH = config_dir() / "config.json"


@dataclass
class Config:
    output_dir: str = ""
    record_system: bool = True          # 录制系统音频（扬声器输出）
    record_mic: bool = True             # 录制麦克风
    speaker_name: str = ""              # 指定扬声器；空 = 系统默认
    mic_name: str = ""                  # 指定麦克风；空 = 系统默认
    auto_detect: bool = True            # 自动探测会议（Teams/腾讯会议）并提示录音

    def __post_init__(self) -> None:
        if not self.output_dir:
            self.output_dir = str(default_output_dir())

    # ---- 持久化 ---------------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        # 只接受已知字段，忽略多余/缺失项
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @property
    def output_path(self) -> Path:
        return Path(self.output_dir)
