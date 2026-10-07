"""Safe text chunking for TTS.

Priority of split points: paragraph → sentence → punctuation → whitespace.
Words are never cut unless a single "word" is longer than the limit (e.g. a
URL), in which case a hard split is the only option.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# End of sentence: . ! ? … (also full-width variants) optionally followed by
# closing quotes/brackets, then whitespace.
_SENTENCE_RE = re.compile(r"(?<=[.!?…。！？])[\"'”’»)\]]*\s+")
# Secondary split points inside a long sentence.
_PUNCT_RE = re.compile(r"(?<=[,;:，；：—–])\s+|\s+(?=[—–]\s)")
_PARAGRAPH_RE = re.compile(r"\n\s*\n")


@dataclass
class Chunk:
    text: str
    ends_paragraph: bool = False
    ends_sentence: bool = True


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(text.replace("\r\n", "\n"))]
    return [" ".join(p.split()) for p in paragraphs if p]


def split_sentences(paragraph: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_RE.split(paragraph)]
    return [p for p in parts if p]


def _split_long(piece: str, max_chars: int) -> list[str]:
    """Split a sentence longer than *max_chars* at punctuation, then spaces."""
    if len(piece) <= max_chars:
        return [piece]
    out: list[str] = []
    for part in _pack([p for p in _PUNCT_RE.split(piece) if p.strip()], max_chars):
        if len(part) <= max_chars:
            out.append(part)
            continue
        # No punctuation small enough – fall back to whitespace.
        out.extend(_pack(part.split(" "), max_chars, hard=True))
    return out


def _pack(pieces: list[str], max_chars: int, hard: bool = False) -> list[str]:
    """Greedily join *pieces* with spaces while staying under *max_chars*."""
    out: list[str] = []
    cur = ""
    for raw in pieces:
        p = raw.strip()
        if not p:
            continue
        if hard and len(p) > max_chars:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(p[i:i + max_chars] for i in range(0, len(p), max_chars))
            continue
        candidate = f"{cur} {p}" if cur else p
        if len(candidate) <= max_chars:
            cur = candidate
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def split_text(
    text: str,
    max_chars: int = 600,
    min_chars: int = 40,
    sentence_aware: bool = True,
    one_sentence_per_chunk: bool = False,
) -> list[Chunk]:
    """Split *text* into chunks no longer than *max_chars*.

    Chunks never cross paragraph boundaries so the caller can insert a
    paragraph pause. ``ends_sentence`` tells whether the chunk finishes on a
    sentence boundary (useful for sentence pauses).
    """
    max_chars = max(20, int(max_chars))
    min_chars = max(0, min(int(min_chars), max_chars // 2))
    chunks: list[Chunk] = []
    for paragraph in split_paragraphs(text):
        sentences = split_sentences(paragraph) if sentence_aware else [paragraph]
        para_chunks: list[Chunk] = []
        if one_sentence_per_chunk:
            for s in sentences:
                parts = _split_long(s, max_chars)
                for i, part in enumerate(parts):
                    para_chunks.append(Chunk(part, ends_sentence=i == len(parts) - 1))
        else:
            cur = ""
            for s in sentences:
                if len(s) > max_chars:
                    if cur:
                        para_chunks.append(Chunk(cur))
                        cur = ""
                    parts = _split_long(s, max_chars)
                    for i, part in enumerate(parts):
                        para_chunks.append(Chunk(part, ends_sentence=i == len(parts) - 1))
                    continue
                candidate = f"{cur} {s}" if cur else s
                if len(candidate) <= max_chars:
                    cur = candidate
                else:
                    para_chunks.append(Chunk(cur))
                    cur = s
            if cur:
                para_chunks.append(Chunk(cur))
            para_chunks = _merge_small(para_chunks, max_chars, min_chars)
        if para_chunks:
            para_chunks[-1].ends_paragraph = True
            para_chunks[-1].ends_sentence = True
        chunks.extend(para_chunks)
    return chunks


def _merge_small(chunks: list[Chunk], max_chars: int, min_chars: int) -> list[Chunk]:
    """Merge chunks shorter than *min_chars* into a neighbour when it fits."""
    if min_chars <= 0 or len(chunks) < 2:
        return chunks
    out: list[Chunk] = []
    for c in chunks:
        if out and len(c.text) < min_chars and len(out[-1].text) + 1 + len(c.text) <= max_chars:
            out[-1] = Chunk(f"{out[-1].text} {c.text}", ends_sentence=c.ends_sentence)
        elif out and len(out[-1].text) < min_chars and len(out[-1].text) + 1 + len(c.text) <= max_chars:
            out[-1] = Chunk(f"{out[-1].text} {c.text}", ends_sentence=c.ends_sentence)
        else:
            out.append(c)
    return out
