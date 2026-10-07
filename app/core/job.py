"""Queue job model."""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any


class JobStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    SKIPPED = "Skipped"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def is_final(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.SKIPPED)

    @property
    def is_runnable(self) -> bool:
        return self in (JobStatus.PENDING, JobStatus.FAILED, JobStatus.CANCELLED)


@dataclass
class Job:
    source: str
    root: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    checked: bool = True
    mode: str = "auto"             # requested: auto / story / conversation
    detected_mode: str = ""        # what auto-detect / the parser resolved
    profile_name: str = ""
    voices: str = ""
    speakers: list[str] = field(default_factory=list)
    model: str = ""
    output_path: str = ""
    status: str = JobStatus.PENDING.value
    progress: int = 0
    error: str = ""
    duration_s: float | None = None
    processing_time_s: float = 0.0
    char_count: int = 0
    note: str = ""                 # e.g. "tts_config.json applied"
    output_override: str = ""      # explicit output file (single-script mode)

    @property
    def source_path(self) -> Path:
        return Path(self.source)

    @property
    def file_name(self) -> str:
        return self.source_path.name

    @property
    def relative_path(self) -> str:
        if self.root:
            try:
                return str(self.source_path.relative_to(self.root))
            except ValueError:
                pass
        return self.file_name

    @property
    def folder(self) -> str:
        rel = Path(self.relative_path).parent
        return "" if str(rel) == "." else str(rel)

    @property
    def status_enum(self) -> JobStatus:
        return JobStatus(self.status)

    @property
    def mode_label(self) -> str:
        if self.mode == "auto":
            return f"Auto → {self.detected_mode.capitalize()}" if self.detected_mode else "Auto"
        return self.mode.capitalize()

    def reset_for_run(self) -> None:
        self.status = JobStatus.PENDING.value
        self.progress = 0
        self.error = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        known = {f.name for f in fields(cls)}
        job = cls(**{k: v for k, v in d.items() if k in known})
        # A job interrupted mid-run (crash / restart) must run again.
        if job.status == JobStatus.PROCESSING.value:
            job.status = JobStatus.PENDING.value
            job.progress = 0
        return job
