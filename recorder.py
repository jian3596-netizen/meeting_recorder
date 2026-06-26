"""音频录制核心模块。

根据配置录制 "系统扬声器输出(loopback)" 与/或 "麦克风" 两路音频，
单声道采集（内存占用小），停止时混音并编码为 MP3 保存。
"""

from __future__ import annotations

import logging
import threading
import wave
from datetime import datetime
from pathlib import Path

import lameenc
import numpy as np
import soundcard as sc

from config import Config

log = logging.getLogger("recorder")

SAMPLERATE = 48000
CHANNELS = 1               # 单声道：会议人声足够，且内存/体积减半
CHUNK = SAMPLERATE // 10   # 100ms 一块
MP3_BITRATE = 256          # kbps，对人声几乎无损
MP3_QUALITY = 2            # 0=最好/最慢，9=最差/最快


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
                log.exception("无法打开系统音频")
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
                log.exception("无法打开麦克风")
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
        stem = f"meeting_{datetime.now():%Y%m%d_%H%M%S}"
        path = out_dir / f"{stem}.mp3"
        try:
            _write_mp3(path, mix, SAMPLERATE)
        except Exception:  # noqa: BLE001  编码失败也不能丢录音，退回 WAV
            log.exception("MP3 编码失败，改存 WAV")
            path = out_dir / f"{stem}.wav"
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
                    data = rec.record(numframes=CHUNK)  # (frames, 1) float32
                    mono = data[:, 0] if data.ndim == 2 else data
                    # 立即转 int16 存储，内存比 float32 再省一半
                    sink.append((np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16))
        except Exception as exc:  # noqa: BLE001
            log.exception("%s 录制中断", label)
            self._errors.append(f"{label} 录制中断: {exc}")

    def _mix(self) -> np.ndarray | None:
        system = _concat(self._system_frames)
        mic = _concat(self._mic_frames)

        tracks = [t for t in (system, mic) if t is not None and len(t) > 0]
        if not tracks:
            return None

        length = min(len(t) for t in tracks)
        acc = np.zeros(length, dtype=np.int32)
        for t in tracks:
            acc += t[:length].astype(np.int32)

        # 防止削波：峰值超过 int16 范围时整体缩放
        peak = int(np.max(np.abs(acc))) if acc.size else 0
        if peak > 32767:
            acc = acc * 32767 // peak
        return acc.astype(np.int16)

    @property
    def errors(self) -> list[str]:
        return list(self._errors)


def _concat(frames: list[np.ndarray]) -> np.ndarray | None:
    if not frames:
        return None
    return np.concatenate(frames, axis=0)


def _write_mp3(path: Path, data: np.ndarray, samplerate: int) -> None:
    """data：单声道 int16 一维数组。"""
    encoder = lameenc.Encoder()
    encoder.set_bit_rate(MP3_BITRATE)
    encoder.set_in_sample_rate(samplerate)
    encoder.set_channels(1)
    encoder.set_quality(MP3_QUALITY)
    mp3 = encoder.encode(np.ascontiguousarray(data, dtype=np.int16).tobytes())
    mp3 += encoder.flush()
    path.write_bytes(bytes(mp3))


def _write_wav(path: Path, data: np.ndarray, samplerate: int) -> None:
    """data：单声道 int16 一维数组。"""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(samplerate)
        wf.writeframes(np.ascontiguousarray(data, dtype=np.int16).tobytes())
