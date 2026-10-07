"""Parser abstractions shared by story and conversation modes."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class ScriptMode(str, Enum):
    AUTO = "auto"
    STORY = "story"
    CONVERSATION = "conversation"

    @property
    def label(self) -> str:
        return {"auto": "Auto", "story": "Story", "conversation": "Conversation"}[self.value]


@dataclass
class ScriptBlock:
    """A run of text spoken by one speaker (``None`` = narrator voice in story mode)."""

    text: str
    speaker: str | None = None


@dataclass
class ParsedScript:
    mode: ScriptMode
    blocks: list[ScriptBlock] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for b in self.blocks:
            if b.speaker and b.speaker not in seen:
                seen.append(b.speaker)
        return seen


class DialogueFormat(ABC):
    """One dialogue syntax (e.g. ``[ANNA]`` tags or ``Anna:`` prefixes).

    New syntaxes are added by subclassing and registering in
    :mod:`app.parsers.conversation_parser` – no other code changes needed.
    """

    name: str = "base"

    @abstractmethod
    def score(self, text: str) -> float:
        """Confidence 0..1 that *text* is written in this format."""

    @abstractmethod
    def parse(self, text: str) -> list[ScriptBlock]:
        """Split *text* into speaker blocks."""
