"""Merge WAV segments with configurable silences (pure Python, lossless)."""
from __future__ import annotations

import logging
import wave
from dataclasses import dataclass
from pathlib import Path

from app.audio.ffmpeg import FFmpegMissingError, run_ffmpeg

log = logging.getLogger("audio.merger")


@dataclass
class MergeItem:
    path: Path
    silence_before_ms: int = 0


@dataclass(frozen=True)
class WavFormat:
    channels: int
    sampwidth: int
    framerate: int


def wav_format(path: Path) -> WavFormat:
    with wave.open(str(path), "rb") as w:
        return WavFormat(w.getnchannels(), w.getsampwidth(), w.getframerate())


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate() or 1
        return w.getnframes() / rate


def _conform(path: Path, target: WavFormat, ffmpeg: str | None, workdir: Path) -> Path:
    """Re-encode *path* to *target* format if it differs."""
    if wav_format(path) == target:
        return path
    if not ffmpeg:
        raise FFmpegMissingError()
    out = workdir / f"{path.stem}.conformed.wav"
    codec = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}[target.sampwidth]
    run_ffmpeg(ffmpeg, ["-i", str(path), "-ac", str(target.channels), "-ar", str(target.framerate),
                        "-c:a", codec, str(out)])
    return out


def merge_wavs(items: list[MergeItem], output: Path, ffmpeg: str | None = None) -> float:
    """Concatenate *items* into *output* (WAV). Returns duration in seconds."""
    if not items:
        raise ValueError("Nothing to merge")
    target = wav_format(items[0].path)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame_bytes = target.channels * target.sampwidth
    silence_byte = b"\x80" if target.sampwidth == 1 else b"\x00"
    total_frames = 0
    with wave.open(str(output), "wb") as out:
        out.setnchannels(target.channels)
        out.setsampwidth(target.sampwidth)
        out.setframerate(target.framerate)
        for idx, item in enumerate(items):
            if idx > 0 and item.silence_before_ms > 0:
                n = int(target.framerate * item.silence_before_ms / 1000)
                out.writeframes(silence_byte * (n * frame_bytes))
                total_frames += n
            src = _conform(item.path, target, ffmpeg, output.parent)
            with wave.open(str(src), "rb") as w:
                while True:
                    data = w.readframes(65536)
                    if not data:
                        break
                    out.writeframes(data)
                    total_frames += len(data) // frame_bytes
    return total_frames / target.framerate
