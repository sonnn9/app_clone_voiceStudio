"""Story mode: the whole text is read by one narrator voice."""
from __future__ import annotations

from app.parsers.base import ParsedScript, ScriptBlock, ScriptMode


def parse_story(text: str) -> ParsedScript:
    text = text.strip()
    blocks = [ScriptBlock(text=text, speaker=None)] if text else []
    return ParsedScript(mode=ScriptMode.STORY, blocks=blocks)
