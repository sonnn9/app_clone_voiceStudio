"""Turns one TXT job into one audio file.

Pipeline::

    read TXT → preprocess → parse (story / conversation) → plan segments
    → generate each segment (resume / cache / retries) → merge WAV + silences
    → encode (mp3/flac/wav) to "<name>.<ext>.part" → atomic rename

This module has no Qt dependency so it can be tested and reused from a CLI.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.api.base_tts_adapter import BaseTTSAdapter
from app.api.errors import TTSError, TTSErrorKind
from app.api.models import VoiceSelection
from app.audio.converter import encode_audio
from app.audio.merger import MergeItem, merge_wavs
from app.audio.metadata import write_tags
from app.core.cache import AudioCache, segment_key
from app.core.folder_config import apply_folder_config, merged_config
from app.core.job import Job, JobStatus
from app.core.output_paths import build_output_path, resolve_existing, suffixed_path
from app.core.preprocess import preprocess_text
from app.core.profiles import NARRATOR_NAMES, GenerationProfile, ProfileStore
from app.core.pronunciation import PronunciationRule
from app.core.settings import AppSettings
from app.parsers.base import ParsedScript, ScriptMode
from app.parsers.detect import parse_script
from app.utils.paths import work_dir
from app.utils.text_io import TextDecodeError, read_text_file
from app.utils.text_splitter import split_text

log = logging.getLogger("batch")


class JobCancelled(Exception):
    pass


class JobSkipped(Exception):
    pass


class JobControl:
    """Pause / cancel signalling shared by all workers of a batch."""

    def __init__(self) -> None:
        self._cancel = threading.Event()
        self._running = threading.Event()
        self._running.set()

    def cancel(self) -> None:
        self._cancel.set()
        self._running.set()  # wake paused workers so they can exit

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def checkpoint(self) -> None:
        while not self._running.wait(0.2):
            pass
        if self._cancel.is_set():
            raise JobCancelled()

    def sleep(self, seconds: float) -> None:
        if self._cancel.wait(max(0.0, seconds)):
            raise JobCancelled()


@dataclass
class Segment:
    index: int
    text: str
    voice: VoiceSelection
    speaker: str | None = None
    silence_before_ms: int = 0


@dataclass
class PreparedJob:
    """Everything known about a job before audio generation."""

    profile: GenerationProfile
    original_text: str
    processed_text: str
    script: ParsedScript
    segments: list[Segment] = field(default_factory=list)
    config_files: list[Path] = field(default_factory=list)


def effective_profile(job: Job, store: ProfileStore, settings: AppSettings) -> tuple[GenerationProfile, list[Path]]:
    base = store.get_or_first(job.profile_name)
    cfg_files: list[Path] = []
    profile = base
    if settings.use_folder_config:
        root = Path(job.root) if job.root else job.source_path.parent
        cfg, cfg_files = merged_config(job.source_path.parent, root, settings.inherit_parent_folder_config)
        profile = apply_folder_config(base, cfg, store)
    if job.mode and job.mode != "auto":
        profile = profile.clone()
        profile.mode = job.mode
    return profile, cfg_files


def plan_segments(
    script: ParsedScript,
    profile: GenerationProfile,
    max_chars: int,
    min_chars: int,
    sentence_aware: bool,
) -> list[Segment]:
    sil = profile.silence
    segments: list[Segment] = []
    one_sentence = sil.sentence_ms > 0 and script.mode == ScriptMode.STORY
    for b_idx, block in enumerate(script.blocks):
        chunks = split_text(block.text, max_chars, min_chars, sentence_aware, one_sentence)
        voice = profile.voice_for(block.speaker) if script.mode == ScriptMode.CONVERSATION else profile.voice
        prev = None
        for c_idx, chunk in enumerate(chunks):
            if not segments:
                pause = 0
            elif c_idx == 0:
                # First chunk of a new block (= a new dialogue turn).
                if block.speaker and block.speaker.upper() in NARRATOR_NAMES:
                    pause = sil.narrator_ms
                elif script.mode == ScriptMode.CONVERSATION:
                    pause = sil.turn_ms
                else:
                    pause = sil.paragraph_ms
            elif prev is not None and prev.ends_paragraph:
                pause = sil.paragraph_ms
            elif prev is not None and prev.ends_sentence:
                pause = sil.sentence_ms
            else:
                pause = 0
            segments.append(Segment(len(segments), chunk.text, voice, block.speaker, pause))
            prev = chunk
    return segments


def prepare_job(
    job: Job,
    store: ProfileStore,
    settings: AppSettings,
    global_rules: list[PronunciationRule],
    max_input_chars: int = 4096,
) -> PreparedJob:
    profile, cfg_files = effective_profile(job, store, settings)
    try:
        original, _enc = read_text_file(job.source_path)
    except FileNotFoundError as e:
        raise ValueError(f"File not found: {job.source}") from e
    rules = [*global_rules, *profile.pronunciation]
    processed = preprocess_text(original, settings.preprocess, rules)
    script = parse_script(processed, profile.mode)
    max_chars = max(50, min(int(settings.max_chunk_chars), int(max_input_chars)))
    segments = plan_segments(script, profile, max_chars, settings.min_chunk_chars, settings.sentence_aware)
    return PreparedJob(profile, original, processed, script, segments, cfg_files)


def analyze_job(job: Job, store: ProfileStore, settings: AppSettings) -> None:
    """Cheap pre-scan for the queue table: detected mode, speakers, voices."""
    try:
        prepared = prepare_job(job, store, settings, [])
    except (TextDecodeError, ValueError, OSError) as e:
        job.error = str(e)
        return
    job.detected_mode = prepared.script.mode.value
    job.speakers = prepared.script.speakers
    job.char_count = len(prepared.processed_text)
    job.model = prepared.profile.engine
    job.voices = prepared.profile.voices_summary(job.speakers if prepared.script.mode == ScriptMode.CONVERSATION else None)
    job.note = "tts_config.json" if prepared.config_files else ""
    fmt = prepared.profile.output_format or settings.output_format
    job.output_path = str(build_output_path(
        job.source_path, Path(job.root) if job.root else None,
        settings.output_mode, settings.custom_output_dir, fmt,
    ))


@dataclass
class ProcessContext:
    adapter: BaseTTSAdapter
    settings: AppSettings
    store: ProfileStore
    global_rules: list[PronunciationRule]
    control: JobControl
    ffmpeg: str | None
    cache: AudioCache | None = None
    on_progress: Callable[[Job], None] = lambda job: None
    # Called when the output exists and the policy is "ask";
    # returns "overwrite" | "skip" | "suffix".
    ask_existing: Callable[[Job, Path], str] = lambda job, path: "skip"


def generate_with_retry(ctx: ProcessContext, text: str, voice: VoiceSelection, model: str,
                        params: dict, label: str) -> bytes:
    attempts = max(0, int(ctx.settings.retry_count)) + 1
    for attempt in range(1, attempts + 1):
        ctx.control.checkpoint()
        try:
            return ctx.adapter.generate(text, voice, model, params, response_format="wav")
        except TTSError as e:
            if e.kind == TTSErrorKind.CANCELLED or ctx.control.cancelled:
                raise JobCancelled() from e
            if e.kind == TTSErrorKind.OUT_OF_MEMORY:
                log.error("%s: GPU out of memory – not retrying. %s", label, e.human())
                raise
            if not e.retryable or attempt >= attempts:
                raise
            delay = ctx.settings.retry_delay(attempt)
            if e.retry_after:
                delay = max(delay, min(e.retry_after, 30.0))
            log.warning("%s: attempt %d/%d failed (%s). Retrying in %.1fs.", label, attempt, attempts, e.human(), delay)
            ctx.control.sleep(delay)
    raise TTSError(TTSErrorKind.UNKNOWN, "Retries exhausted")  # pragma: no cover


def process_job(job: Job, ctx: ProcessContext) -> None:
    """Run *job* to completion. Updates the job in place; never raises."""
    started = time.monotonic()
    job.status = JobStatus.PROCESSING.value
    job.progress = 0
    job.error = ""
    ctx.on_progress(job)
    s = ctx.settings
    try:
        ctx.control.checkpoint()
        caps = ctx.adapter.get_capabilities(store_engine(job, ctx))
        prepared = prepare_job(job, ctx.store, s, ctx.global_rules, caps.max_input_chars)
        profile = prepared.profile
        job.detected_mode = prepared.script.mode.value
        job.speakers = prepared.script.speakers
        job.model = profile.engine
        job.voices = profile.voices_summary(job.speakers if prepared.script.mode == ScriptMode.CONVERSATION else None)
        if not prepared.segments:
            raise ValueError("The file contains no text to read.")

        if job.output_override:
            target = Path(job.output_override)
            fmt = target.suffix.lstrip(".").lower() or "mp3"
            out_path, decision = target, "overwrite"  # the user picked this file explicitly
        else:
            fmt = (profile.output_format or s.output_format).lower()
            target = build_output_path(job.source_path, Path(job.root) if job.root else None,
                                       s.output_mode, s.custom_output_dir, fmt)
            out_path, decision = resolve_existing(target, s.existing_behavior)
        if decision == "ask":
            answer = ctx.ask_existing(job, target)
            if answer == "overwrite":
                out_path = target
            elif answer == "suffix":
                out_path = suffixed_path(target)
            else:
                out_path = None
        if out_path is None:
            job.output_path = str(target)
            raise JobSkipped("Output already exists")
        job.output_path = str(out_path)

        log.info("START %s | model=%s | voices=%s | mode=%s | segments=%d",
                 job.source, profile.engine, job.voices, job.detected_mode, len(prepared.segments))

        jdir = work_dir() / job.id
        jdir.mkdir(parents=True, exist_ok=True)
        params = {k: v for k, v in profile.params.items() if v is not None}
        items: list[MergeItem] = []
        total = len(prepared.segments)
        for seg in prepared.segments:
            ctx.control.checkpoint()
            key = segment_key(seg.text, seg.voice.key, seg.voice.instruct, profile.engine, params)
            seg_file = jdir / f"{seg.index:04d}_{key[:16]}.wav"
            if not seg_file.is_file():  # not already generated in an earlier attempt
                cached = ctx.cache.get(key) if (ctx.cache and s.cache_enabled) else None
                if cached:
                    shutil.copyfile(cached, seg_file)
                else:
                    label = f"{job.relative_path} [{seg.index + 1}/{total}]"
                    audio = generate_with_retry(ctx, seg.text, seg.voice, profile.engine, params, label)
                    tmp = seg_file.with_suffix(".part")
                    tmp.write_bytes(audio)
                    os.replace(tmp, seg_file)
                    if ctx.cache and s.cache_enabled:
                        ctx.cache.put(key, seg_file)
            items.append(MergeItem(seg_file, seg.silence_before_ms))
            job.progress = int((seg.index + 1) / total * 90)
            ctx.on_progress(job)

        ctx.control.checkpoint()
        merged = jdir / "merged.wav"
        try:
            job.duration_s = merge_wavs(items, merged, ctx.ffmpeg)
        except Exception as e:
            raise RuntimeError(f"Merge failed: {e}") from e
        out_path.parent.mkdir(parents=True, exist_ok=True)
        part = out_path.with_name(out_path.name + ".part")
        try:
            encode_audio(merged, part, fmt, ctx.ffmpeg, s.mp3_bitrate_kbps, s.normalize_volume)
            if s.write_metadata:
                write_tags(part, job.source_path.stem, fmt)
            os.replace(part, out_path)
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
        shutil.rmtree(jdir, ignore_errors=True)
        job.status = JobStatus.COMPLETED.value
        job.progress = 100
        log.info("DONE  %s → %s (%.1fs audio, %.1fs elapsed)", job.source, out_path,
                 job.duration_s or 0, time.monotonic() - started)
    except JobSkipped as e:
        job.status = JobStatus.SKIPPED.value
        job.error = str(e)
        job.progress = 100
        log.info("SKIP  %s (%s)", job.source, e)
    except JobCancelled:
        job.status = JobStatus.CANCELLED.value
        job.error = "Cancelled"
        log.info("CANCEL %s", job.source)
    except TTSError as e:
        job.status = JobStatus.FAILED.value
        job.error = f"{e.human()} — {e.hint}" if e.hint else e.human()
        log.error("FAIL  %s: %s", job.source, e.human())
    except TextDecodeError as e:
        job.status = JobStatus.FAILED.value
        job.error = str(e)
        log.error("FAIL  %s: %s", job.source, e)
    except Exception as e:  # one bad file must never stop the batch
        job.status = JobStatus.FAILED.value
        job.error = str(e) or e.__class__.__name__
        log.exception("FAIL  %s", job.source)
    finally:
        job.processing_time_s = time.monotonic() - started
        ctx.on_progress(job)


def store_engine(job: Job, ctx: ProcessContext) -> str:
    profile, _ = effective_profile(job, ctx.store, ctx.settings)
    return profile.engine
