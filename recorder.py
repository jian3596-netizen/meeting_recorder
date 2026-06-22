"""音频录制核心模块。

根据配置录制 "系统扬声器输出(loopback)" 与/或 "麦克风" 两路音频，
停止时混音并保存为单个 WAV 文件。
"""

from __future__ import annotations

import threading
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import soundcard as sc

from config import Config

SAMPLERATE = 48000
CHANNELS = 2
CHUNK = SAMPLERATE // 10  # 100ms 一块


class RecorderError(Exception):
    """录音相关的可向用户展示的错误。"""


class AudioRecorder:
    """管理一次会议录音的生命周期。"""

    def __init__(self, config: Config) -> None:
        self.config = config

        self._recording = False
        self._threads: list[threading.Thread] = []
        self._system_frames: list[np.ndarray] = []
        self._mic_frames: list[np.ndarray] = []
        self._errors: list[str] = []
        self.last_file: Path | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def output_dir(self) -> Path:
        return self.config.output_path

    # ---- 录音控制 -------------------------------------------------------
    def start(self) -> None:
        if self._recording:
            return

        if not (self.config.record_system or self.config.record_mic):
            raise RecorderError("请至少在「设置 → 录音源」中启用一个录音源")

        self._system_frames = []
        self._mic_frames = []
        self._errors = []
        self._threads = []
        self._recording = True

        if self.config.record_system:
            try:
                loopback = self._resolve_loopback()
                self._threads.append(
                    threading.Thread(
                        target=self._capture,
                        args=(loopback, self._system_frames, "系统音频"),
                        daemon=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"无法打开系统音频: {exc}")

        if self.config.record_mic:
            try:
                mic = self._resolve_mic()
                self._threads.append(
                    threading.Thread(
                        target=self._capture,
                        args=(mic, self._mic_frames, "麦克风"),
                        daemon=True,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self._errors.append(f"无法打开麦克风: {exc}")

        if not self._threads:
            self._recording = False
            raise RecorderError("；".join(self._errors) or "没有可用的录音设备")

        for t in self._threads:
            t.start()

    def stop(self) -> Path | None:
        """停止录音，混音并写入文件。返回文件路径（无音频时返回 None）。"""
        if not self._recording:
            return None

        self._recording = False
        for t in self._threads:
            t.join(timeout=5)
        self._threads = []

        mix = self._mix()
        if mix is None:
            return None

        out_dir = self.config.output_path
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"meeting_{datetime.now():%Y%m%d_%H%M%S}.wav"
        _write_wav(path, mix, SAMPLERATE)
        self.last_file = path
        return path

    # ---- 设备解析 -------------------------------------------------------
    def _resolve_loopback(self):
        name = self.config.speaker_name
        speaker = sc.get_speaker(name) if name else sc.default_speaker()
        if speaker is None:
            raise RecorderError("找不到指定的扬声器设备")
        return sc.get_microphone(id=str(speaker.name), include_loopback=True)

    def _resolve_mic(self):
        name = self.config.mic_name
        mic = sc.get_microphone(name) if name else sc.default_microphone()
        if mic is None:
            raise RecorderError("找不到指定的麦克风设备")
        return mic

    # ---- 内部实现 -------------------------------------------------------
    def _capture(self, microphone, sink: list[np.ndarray], label: str) -> None:
        try:
            with microphone.recorder(samplerate=SAMPLERATE, channels=CHANNELS) as rec:
                while self._recording:
                    sink.append(rec.record(numframes=CHUNK))
        except Exception as exc:  # noqa: BLE001
            self._errors.append(f"{label} 录制中断: {exc}")

    def _mix(self) -> np.ndarray | None:
        system = _concat(self._system_frames)
        mic = _concat(self._mic_frames)

        tracks = [t for t in (system, mic) if t is not None and len(t) > 0]
        if not tracks:
            return None

        length = min(len(t) for t in tracks)
        mixed = np.zeros((length, CHANNELS), dtype=np.float32)
        for t in tracks:
            mixed += t[:length]

        # 防止削波：峰值超过 1 时整体缩放
        peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
        if peak > 1.0:
            mixed /= peak
        return mixed

    @property
    def errors(self) -> list[str]:
        return list(self._errors)


def _concat(frames: list[np.ndarray]) -> np.ndarray | None:
    if not frames:
        return None
    return np.concatenate(frames, axis=0)


def _write_wav(path: Path, data: np.ndarray, samplerate: int) -> None:
    clipped = np.clip(data, -1.0, 1.0)
    ints = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(data.shape[1])
        wf.setsampwidth(2)  # int16
        wf.setframerate(samplerate)
        wf.writeframes(ints.tobytes())
