"""Final encoding (WAV → MP3/FLAC/WAV) with optional gentle loudness normalisation."""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from app.audio.ffmpeg import FFmpegMissingError, run_ffmpeg

log = logging.getLogger("audio.converter")

SUPPORTED_FORMATS = ("mp3", "wav", "flac")
# EBU R128 speech target; linear mode = a single gain change, no compression.
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def _measure_loudness(ffmpeg: str, src: Path) -> dict[str, str] | None:
    try:
        proc = run_ffmpeg(ffmpeg, ["-i", str(src), "-af", f"{_LOUDNORM}:print_format=json", "-f", "null", "-"])
    except RuntimeError as e:
        log.warning("Loudness measurement failed: %s", e)
        return None
    text = proc.stderr.decode("utf-8", "replace")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _normalize_filter(ffmpeg: str, src: Path) -> str | None:
    stats = _measure_loudness(ffmpeg, src)
    if not stats:
        return None
    return (
        f"{_LOUDNORM}:measured_I={stats['input_i']}:measured_TP={stats['input_tp']}"
        f":measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}"
        f":offset={stats.get('target_offset', '0')}:linear=true"
    )


def encode_audio(
    src_wav: Path,
    dest: Path,
    fmt: str,
    ffmpeg: str | None,
    bitrate_kbps: int = 192,
    normalize: bool = False,
) -> None:
    """Write *src_wav* to *dest* in *fmt*. *dest* should be a temporary path."""
    fmt = fmt.lower()
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported output format: {fmt}")
    if fmt == "wav" and not normalize:
        shutil.copyfile(src_wav, dest)
        return
    if not ffmpeg:
        raise FFmpegMissingError()
    args = ["-i", str(src_wav)]
    if normalize:
        flt = _normalize_filter(ffmpeg, src_wav)
        if flt:
            # loudnorm resamples internally to 192 kHz; restore the source rate.
            from app.audio.merger import wav_format
            args += ["-af", flt, "-ar", str(wav_format(src_wav).framerate)]
    if fmt == "mp3":
        args += ["-c:a", "libmp3lame", "-b:a", f"{int(bitrate_kbps)}k", "-f", "mp3"]
    elif fmt == "flac":
        args += ["-c:a", "flac", "-f", "flac"]
    else:
        args += ["-c:a", "pcm_s16le", "-f", "wav"]
    args.append(str(dest))
    run_ffmpeg(ffmpeg, args)
