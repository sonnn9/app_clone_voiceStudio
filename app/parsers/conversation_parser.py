"""Conversation mode parsers.

Supported syntaxes::

    [ANNA]                      Anna: Hello.
    Hi Tom!                     Tom: Hi Anna.

Each syntax is a :class:`DialogueFormat`; :func:`parse_conversation` picks the
best-scoring one. Parsing is independent of the TTS/API code.
"""
from __future__ import annotations

import re

from app.parsers.base import DialogueFormat, ParsedScript, ScriptBlock, ScriptMode

# A speaker name: letters (any script, incl. Vietnamese), digits, spaces,
# dot, dash, underscore, apostrophe. Max 40 chars.
_NAME = r"[^\W\d_][\w .'\-]{0,39}"


def normalize_speaker(name: str) -> str:
    return " ".join(name.strip().split()).upper()


class BracketTagFormat(DialogueFormat):
    """``[SPEAKER]`` on its own line, followed by that speaker's text."""

    name = "bracket"
    _TAG = re.compile(rf"^\s*\[\s*({_NAME})\s*\]\s*(.*)$", re.UNICODE)

    def score(self, text: str) -> float:
        tags = [m.group(1) for line in text.splitlines() if (m := self._TAG.match(line))]
        if not tags:
            return 0.0
        distinct = {normalize_speaker(t) for t in tags}
        if len(distinct) >= 2 or len(tags) >= 2:
            return 1.0
        return 0.5  # a single lone tag is not enough to auto-switch modes

    def parse(self, text: str) -> list[ScriptBlock]:
        blocks: list[ScriptBlock] = []
        speaker: str | None = None
        buf: list[str] = []

        def flush() -> None:
            body = "\n".join(buf).strip()
            if body:
                blocks.append(ScriptBlock(text=body, speaker=speaker))

        for line in text.splitlines():
            m = self._TAG.match(line)
            if m:
                flush()
                buf = []
                speaker = normalize_speaker(m.group(1))
                rest = m.group(2).strip()
                if rest:
                    buf.append(rest)
            else:
                buf.append(line)
        flush()
        return blocks


class ColonPrefixFormat(DialogueFormat):
    """``Speaker: text`` lines. Continuation lines belong to the last speaker."""

    name = "colon"
    _LINE = re.compile(rf"^\s*({_NAME}?)\s*:\s+(\S.*)$", re.UNICODE)
    _MAX_NAME_WORDS = 3

    def _match(self, line: str) -> re.Match | None:
        m = self._LINE.match(line)
        if not m:
            return None
        name = m.group(1).strip()
        if not name or len(name.split()) > self._MAX_NAME_WORDS:
            return None
        # Names start with an uppercase letter (avoids "note: ..." prose).
        if not name[0].isupper():
            return None
        return m

    def score(self, text: str) -> float:
        lines = [ln for ln in text.splitlines() if ln.strip()]
        if not lines:
            return 0.0
        matches = [m for ln in lines if (m := self._match(ln))]
        speakers = {normalize_speaker(m.group(1)) for m in matches}
        if len(speakers) < 2 or len(matches) < 2:
            return 0.0
        ratio = len(matches) / len(lines)
        return 0.9 if ratio >= 0.5 else 0.0

    def parse(self, text: str) -> list[ScriptBlock]:
        blocks: list[ScriptBlock] = []
        for line in text.splitlines():
            m = self._match(line)
            if m:
                blocks.append(ScriptBlock(text=m.group(2).strip(), speaker=normalize_speaker(m.group(1))))
            elif line.strip():
                if blocks:
                    blocks[-1].text += "\n" + line.strip()
                else:
                    blocks.append(ScriptBlock(text=line.strip(), speaker=None))
            elif blocks:
                blocks[-1].text += "\n"
        for b in blocks:
            b.text = b.text.strip()
        return [b for b in blocks if b.text]


# Registry – order matters only for equal scores.
DIALOGUE_FORMATS: list[DialogueFormat] = [BracketTagFormat(), ColonPrefixFormat()]


def best_format(text: str) -> tuple[DialogueFormat | None, float]:
    best: DialogueFormat | None = None
    best_score = 0.0
    for fmt in DIALOGUE_FORMATS:
        s = fmt.score(text)
        if s > best_score:
            best, best_score = fmt, s
    return best, best_score


def parse_conversation(text: str, default_speaker: str = "NARRATOR") -> ParsedScript:
    fmt, _ = best_format(text)
    if fmt is None:
        blocks = [ScriptBlock(text=text.strip(), speaker=default_speaker)] if text.strip() else []
    else:
        blocks = fmt.parse(text)
        for b in blocks:
            if b.speaker is None:
                b.speaker = default_speaker
    return ParsedScript(mode=ScriptMode.CONVERSATION, blocks=blocks)


def detect_speakers(text: str) -> list[str]:
    return parse_conversation(text).speakers
