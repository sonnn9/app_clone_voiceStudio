"""Batch summary and CSV export."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from app.core.job import Job, JobStatus


def summarize(jobs: list[Job]) -> dict[str, int]:
    counts = Counter(j.status for j in jobs if j.checked)
    total = sum(1 for j in jobs if j.checked)
    done = counts[JobStatus.COMPLETED.value] + counts[JobStatus.SKIPPED.value] + counts[JobStatus.FAILED.value]
    return {
        "total": total,
        "completed": counts[JobStatus.COMPLETED.value],
        "failed": counts[JobStatus.FAILED.value],
        "skipped": counts[JobStatus.SKIPPED.value],
        "cancelled": counts[JobStatus.CANCELLED.value],
        "processing": counts[JobStatus.PROCESSING.value],
        "pending": counts[JobStatus.PENDING.value],
        "done": done,
        "remaining": total - done,
    }


def export_csv(jobs: list[Job], path: Path) -> None:
    # utf-8-sig so Excel shows Vietnamese file names correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["File", "Input path", "Output path", "Mode", "Profile", "Voice", "Model",
                    "Status", "Error", "Processing time (s)", "Duration (s)"])
        for j in jobs:
            w.writerow([
                j.relative_path, j.source, j.output_path, j.mode_label, j.profile_name, j.voices,
                j.model, j.status, j.error, f"{j.processing_time_s:.1f}",
                f"{j.duration_s:.1f}" if j.duration_s else "",
            ])
