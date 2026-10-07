"""Batch queue: runs jobs on worker threads and reports to the UI via Qt signals."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from app.api.base_tts_adapter import BaseTTSAdapter
from app.audio.ffmpeg import find_ffmpeg
from app.core.cache import AudioCache
from app.core.job import Job, JobStatus
from app.core.job_processor import JobControl, ProcessContext, process_job
from app.core.profiles import ProfileStore
from app.core.pronunciation import PronunciationStore
from app.core.report import summarize
from app.core.session import save_session
from app.core.settings import AppSettings

log = logging.getLogger("batch")


class BatchManager(QObject):
    job_updated = Signal(str)               # job id
    stats_changed = Signal(dict)
    current_file_changed = Signal(str)
    running_changed = Signal(bool)
    paused_changed = Signal(bool)
    batch_finished = Signal(dict)
    ask_existing = Signal(str, str)         # job id, output path
    _all_done = Signal()

    def __init__(
        self,
        adapter: BaseTTSAdapter,
        settings: AppSettings,
        profiles: ProfileStore,
        pronunciation: PronunciationStore,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.adapter = adapter
        self.settings = settings
        self.profiles = profiles
        self.pronunciation = pronunciation
        self.jobs: list[Job] = []
        self.cache = AudioCache()
        self._control: JobControl | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._active = 0
        self._dirty = False
        # "Ask" dialog plumbing (worker waits for the UI answer).
        self._ask_event = threading.Event()
        self._ask_lock = threading.Lock()
        self._ask_answer = "skip"
        self._ask_remember: str | None = None

        self._all_done.connect(self._finish, Qt.ConnectionType.QueuedConnection)

        self._autosave = QTimer(self)
        self._autosave.setInterval(5000)
        self._autosave.timeout.connect(self._save_if_dirty)
        self._autosave.start()

    # --------------------------------------------------------------- queue ops
    def job(self, job_id: str) -> Job | None:
        return next((j for j in self.jobs if j.id == job_id), None)

    def add_jobs(self, jobs: list[Job]) -> list[Job]:
        existing = {Path(j.source).resolve() for j in self.jobs}
        added = [j for j in jobs if Path(j.source).resolve() not in existing]
        self.jobs.extend(added)
        self.mark_dirty()
        return added

    def remove_jobs(self, ids: set[str]) -> None:
        if self.is_running:
            ids = {i for i in ids if (j := self.job(i)) and j.status != JobStatus.PROCESSING.value}
        self.jobs = [j for j in self.jobs if j.id not in ids]
        self.mark_dirty()

    def clear(self) -> None:
        if not self.is_running:
            self.jobs = []
            self.mark_dirty()

    def mark_dirty(self) -> None:
        self._dirty = True
        self.stats_changed.emit(summarize(self.jobs))

    def _save_if_dirty(self) -> None:
        if self._dirty:
            self._dirty = False
            save_session(self.jobs)

    def save_now(self) -> None:
        self._dirty = False
        save_session(self.jobs)

    # ------------------------------------------------------------------ state
    @property
    def is_running(self) -> bool:
        return self._executor is not None

    @property
    def is_paused(self) -> bool:
        return bool(self._control and self._control.paused)

    # ------------------------------------------------------------ run control
    def start(self, retry_ids: set[str] | None = None) -> int:
        """Queue checked runnable jobs (or *retry_ids*). Returns the count."""
        if self.is_running:
            return 0
        if retry_ids is not None:
            todo = [j for j in self.jobs if j.id in retry_ids and j.status != JobStatus.COMPLETED.value]
        else:
            todo = [j for j in self.jobs if j.checked and JobStatus(j.status).is_runnable]
        if not todo:
            return 0
        for j in todo:
            j.reset_for_run()
            self.job_updated.emit(j.id)
        self.adapter.reset_cancel()
        self._control = JobControl()
        self._ask_remember = None
        workers = max(1, min(4, int(self.settings.concurrency)))
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tts")
        ctx = ProcessContext(
            adapter=self.adapter,
            settings=self.settings,
            store=self.profiles,
            global_rules=list(self.pronunciation.rules),
            control=self._control,
            ffmpeg=find_ffmpeg(self.settings.ffmpeg_path),
            cache=self.cache,
            on_progress=self._on_progress,
            ask_existing=self._ask_existing_blocking,
        )
        with self._lock:
            self._active = len(todo)
        log.info("Batch started: %d job(s), concurrency=%d", len(todo), workers)
        self.running_changed.emit(True)
        self.paused_changed.emit(False)
        for j in todo:
            self._executor.submit(self._run_one, j, ctx)
        self.mark_dirty()
        return len(todo)

    def _run_one(self, job: Job, ctx: ProcessContext) -> None:
        try:
            if ctx.control.cancelled:
                job.status = JobStatus.CANCELLED.value
                job.error = "Cancelled"
                self._on_progress(job)
            else:
                self.current_file_changed.emit(job.relative_path)
                process_job(job, ctx)
        except Exception:  # pragma: no cover - process_job never raises
            log.exception("Worker crashed on %s", job.source)
            job.status = JobStatus.FAILED.value
            self._on_progress(job)
        finally:
            with self._lock:
                self._active -= 1
                finished = self._active == 0
            if finished:
                self._all_done.emit()  # queued → handled on the GUI thread

    def _on_progress(self, job: Job) -> None:
        self._dirty = True
        self.job_updated.emit(job.id)
        self.stats_changed.emit(summarize(self.jobs))

    def _finish(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False)
        self._executor = None
        self._control = None
        self.save_now()
        stats = summarize(self.jobs)
        log.info("Batch finished: %s", stats)
        self.running_changed.emit(False)
        self.paused_changed.emit(False)
        self.current_file_changed.emit("")
        self.batch_finished.emit(stats)

    def pause(self) -> None:
        if self._control:
            self._control.pause()
            log.info("Batch paused")
            self.paused_changed.emit(True)

    def resume(self) -> None:
        if self._control:
            self._control.resume()
            log.info("Batch resumed")
            self.paused_changed.emit(False)

    def cancel(self) -> None:
        if self._control:
            log.info("Batch cancel requested")
            self._control.cancel()
            self.adapter.cancel()
            self._ask_answer = "skip"
            self._ask_event.set()

    # --------------------------------------------------- "ask" existing files
    def _ask_existing_blocking(self, job: Job, path: Path) -> str:
        with self._ask_lock:  # one dialog at a time
            if self._ask_remember:
                return self._ask_remember
            if self._control and self._control.cancelled:
                return "skip"
            self._ask_event.clear()
            self.ask_existing.emit(job.id, str(path))
            self._ask_event.wait()
            return self._ask_answer

    def answer_existing(self, answer: str, apply_to_all: bool) -> None:
        self._ask_answer = answer
        if apply_to_all:
            self._ask_remember = answer
        self._ask_event.set()
