"""Batch session persistence so an interrupted batch can be resumed."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.job import Job, JobStatus
from app.utils.paths import session_dir
from app.utils.text_io import load_json, save_json

log = logging.getLogger("core.session")

SESSION_FILE = "current_session.json"


def save_session(jobs: list[Job], extra: dict[str, Any] | None = None) -> None:
    data = {
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "jobs": [j.to_dict() for j in jobs],
        **(extra or {}),
    }
    try:
        save_json(session_dir() / SESSION_FILE, data)
    except OSError as e:
        log.warning("Could not save session: %s", e)


def load_session() -> tuple[list[Job], dict[str, Any]]:
    data = load_json(session_dir() / SESSION_FILE, {})
    jobs = []
    for d in data.get("jobs", []) if isinstance(data, dict) else []:
        try:
            jobs.append(Job.from_dict(d))
        except TypeError as e:
            log.warning("Skipping corrupt session entry: %s", e)
    return jobs, data if isinstance(data, dict) else {}


def has_unfinished(jobs: list[Job]) -> bool:
    return any(j.checked and not JobStatus(j.status).is_final for j in jobs)


def clear_session() -> None:
    try:
        (session_dir() / SESSION_FILE).unlink(missing_ok=True)
    except OSError:
        pass
