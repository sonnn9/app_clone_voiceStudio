"""Text preprocessing before synthesis. Never touches the source file."""
from __future__ import annotations

import re
from typing import Iterable

from app.core.pronunciation import PronunciationRule, apply_rules
from app.core.settings import PreprocessOptions

_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "‘": "'", "’": "'", "‚": "'", "«": '"', "»": '"'})


def preprocess_text(
    text: str,
    options: PreprocessOptions,
    rules: Iterable[PronunciationRule] = (),
) -> str:
    """Return the text actually sent to the TTS engine.

    Only whitespace/quote normalisation and explicit user rules are applied, so
    the meaning of the text is never changed.
    """
    if options.normalize_line_endings:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("﻿", "")
    if options.collapse_spaces:
        text = re.sub(r"[ \t ]+", " ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
    if options.remove_extra_blank_lines:
        text = re.sub(r"\n{3,}", "\n\n", text)
    if options.convert_smart_quotes:
        text = text.translate(_SMART_QUOTES)
    if options.apply_pronunciation:
        text = apply_rules(text, rules)
    return text.strip()
