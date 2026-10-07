"""Pronunciation dictionary: "WSC" → "World Scholar's Cup"."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable

from app.utils.paths import pronunciation_file
from app.utils.text_io import load_json, save_json

log = logging.getLogger("core.pronunciation")


@dataclass
class PronunciationRule:
    original: str
    replacement: str
    whole_word: bool = True
    case_sensitive: bool = True
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "original": self.original,
            "replacement": self.replacement,
            "whole_word": self.whole_word,
            "case_sensitive": self.case_sensitive,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PronunciationRule":
        return cls(
            original=str(d.get("original", "")),
            replacement=str(d.get("replacement", "")),
            whole_word=bool(d.get("whole_word", True)),
            case_sensitive=bool(d.get("case_sensitive", True)),
            enabled=bool(d.get("enabled", True)),
        )

    def pattern(self) -> re.Pattern[str] | None:
        if not self.original:
            return None
        body = re.escape(self.original)
        if self.whole_word:
            # \b does not work well next to punctuation; use look-arounds on word chars.
            body = rf"(?<!\w){body}(?!\w)"
        flags = re.UNICODE | (0 if self.case_sensitive else re.IGNORECASE)
        return re.compile(body, flags)


def apply_rules(text: str, rules: Iterable[PronunciationRule]) -> str:
    """Apply rules longest-first so "PECC1" wins over "EC"."""
    active = [r for r in rules if r.enabled and r.original]
    active.sort(key=lambda r: len(r.original), reverse=True)
    if not active:
        return text
    # Single pass with alternation: a replacement is never re-processed by
    # another rule (prevents "EC" rewriting part of "E C" output).
    patterns = [(r.pattern(), r.replacement) for r in active]
    # Flags differ per rule, so honour case-insensitivity inline.
    parts = []
    for i, (p, _) in enumerate(patterns):
        if p is None:
            continue
        inline = "(?i:" if p.flags & re.IGNORECASE else "(?:"
        parts.append(f"(?P<r{i}>{inline}{p.pattern}))")
    combined = "|".join(parts)
    regex = re.compile(combined, re.UNICODE)

    def _sub(m: re.Match[str]) -> str:
        for name, value in m.groupdict().items():
            if value is not None:
                return patterns[int(name[1:])][1]
        return m.group(0)

    return regex.sub(_sub, text)


class PronunciationStore:
    """Global rules (profile-specific rules live inside each profile)."""

    def __init__(self) -> None:
        self.rules: list[PronunciationRule] = []
        self.load()

    def load(self) -> None:
        data = load_json(pronunciation_file(), [])
        self.rules = [PronunciationRule.from_dict(d) for d in data if isinstance(d, dict)]

    def save(self) -> None:
        try:
            save_json(pronunciation_file(), [r.to_dict() for r in self.rules])
        except OSError as e:
            log.error("Could not save pronunciation rules: %s", e)
