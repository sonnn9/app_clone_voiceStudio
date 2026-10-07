"""Automatic script-type detection and the single parse entry point."""
from __future__ import annotations

from app.parsers.base import ParsedScript, ScriptMode
from app.parsers.conversation_parser import best_format, parse_conversation
from app.parsers.story_parser import parse_story

CONVERSATION_THRESHOLD = 0.6


def detect_mode(text: str) -> ScriptMode:
    _, score = best_format(text)
    return ScriptMode.CONVERSATION if score >= CONVERSATION_THRESHOLD else ScriptMode.STORY


def resolve_mode(requested: ScriptMode | str, text: str) -> ScriptMode:
    mode = ScriptMode(requested)
    return detect_mode(text) if mode == ScriptMode.AUTO else mode


def parse_script(text: str, mode: ScriptMode | str) -> ParsedScript:
    resolved = resolve_mode(mode, text)
    if resolved == ScriptMode.CONVERSATION:
        return parse_conversation(text)
    return parse_story(text)
