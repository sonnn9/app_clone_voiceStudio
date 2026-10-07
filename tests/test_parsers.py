"""Story / conversation parsing, speaker detection and chunk splitting."""
from app.core.profiles import GenerationProfile, SilenceSettings
from app.api.models import VoiceSelection
from app.core.job_processor import plan_segments
from app.parsers.base import ScriptMode
from app.parsers.conversation_parser import detect_speakers, parse_conversation
from app.parsers.detect import detect_mode, parse_script
from app.parsers.story_parser import parse_story
from app.utils.text_splitter import split_sentences, split_text

BRACKET = """[NARRATOR]
Today we are going to learn about travelling.

[ANNA]
Hi Tom! Where did you go last weekend?

[TOM]
I went to Da Nang with my family.

[ANNA]
Was it fun?

[TOM]
Yes! It was amazing.
"""

COLON = """Anna: Hello.
Tom: Hi Anna.
Anna: How are you?
"""

STORY = """Once upon a time, there was a small rabbit...

She lived near the river. Lưu ý: this colon line is prose."""


def test_story_parsing_single_block():
    s = parse_story(STORY)
    assert s.mode == ScriptMode.STORY
    assert len(s.blocks) == 1 and s.blocks[0].speaker is None


def test_bracket_conversation():
    s = parse_conversation(BRACKET)
    assert [b.speaker for b in s.blocks] == ["NARRATOR", "ANNA", "TOM", "ANNA", "TOM"]
    assert s.blocks[1].text == "Hi Tom! Where did you go last weekend?"


def test_speaker_detection_unique_ordered():
    assert detect_speakers(BRACKET) == ["NARRATOR", "ANNA", "TOM"]


def test_colon_conversation():
    s = parse_conversation(COLON)
    assert [b.speaker for b in s.blocks] == ["ANNA", "TOM", "ANNA"]
    assert s.blocks[1].text == "Hi Anna."


def test_vietnamese_speaker_names():
    text = "[CÔ GIÁO]\nChào các em.\n\n[HỌC SINH]\nChúng em chào cô ạ."
    assert detect_speakers(text) == ["CÔ GIÁO", "HỌC SINH"]


def test_auto_detect_modes():
    assert detect_mode(BRACKET) == ScriptMode.CONVERSATION
    assert detect_mode(COLON) == ScriptMode.CONVERSATION
    assert detect_mode(STORY) == ScriptMode.STORY
    # A single stray tag is not a conversation.
    assert detect_mode("[Music]\nThe story begins here. It is long.") == ScriptMode.STORY


def test_manual_override():
    assert parse_script(BRACKET, "story").mode == ScriptMode.STORY
    assert parse_script(STORY, "conversation").mode == ScriptMode.CONVERSATION


def test_sentence_split():
    assert split_sentences("Hello there. How are you? Fine!") == ["Hello there.", "How are you?", "Fine!"]


def test_chunks_respect_limit_and_words():
    text = ("This is a fairly long sentence that keeps going, with commas, clauses and more words " * 12).strip()
    chunks = split_text(text, max_chars=120, min_chars=0)
    assert all(len(c.text) <= 120 for c in chunks)
    # No word is cut: every chunk boundary falls between words.
    words = text.split()
    assert " ".join(c.text for c in chunks).split() == words


def test_chunks_prefer_paragraph_and_sentence_boundaries():
    text = "First sentence. Second sentence.\n\nNew paragraph here."
    chunks = split_text(text, max_chars=200, min_chars=0)
    assert [c.text for c in chunks] == ["First sentence. Second sentence.", "New paragraph here."]
    assert chunks[0].ends_paragraph and chunks[1].ends_paragraph


def test_chunks_pack_sentences():
    text = "Alpha one. Beta two. Gamma three."
    chunks = split_text(text, max_chars=22, min_chars=0)
    assert [c.text for c in chunks] == ["Alpha one. Beta two.", "Gamma three."]


def test_hard_split_only_for_giant_word():
    giant = "x" * 50
    chunks = split_text(f"short {giant} end", max_chars=20, min_chars=0)
    assert all(len(c.text) <= 20 for c in chunks)


def test_min_chunk_merge():
    long = "A long enough sentence is here for testing."
    # Packing alone would split here; the 3-char tail is merged because it fits.
    chunks = split_text(f"{long} Second sentence of decent size. Ok.", max_chars=80, min_chars=10)
    assert all(len(c.text) >= 10 for c in chunks)
    # When merging would exceed the maximum, the short chunk is kept as is.
    chunks = split_text(f"{long} Ok.", max_chars=45, min_chars=10)
    assert [c.text for c in chunks] == [long, "Ok."]


def test_plan_segments_conversation_voices_and_silence():
    narrator = VoiceSelection("profile:n", "Narr")
    anna = VoiceSelection("profile:a", "Anna")
    profile = GenerationProfile(
        name="t", voice=narrator, speaker_voices={"ANNA": anna},
        silence=SilenceSettings(turn_ms=300, paragraph_ms=600, narrator_ms=900),
    )
    segs = plan_segments(parse_conversation(BRACKET), profile, 400, 0, True)
    assert segs[0].voice == narrator and segs[0].silence_before_ms == 0
    assert segs[1].voice == anna and segs[1].silence_before_ms == 300
    assert segs[2].voice == narrator  # TOM unmapped → default voice


def test_plan_segments_story_paragraph_pause():
    profile = GenerationProfile(name="t", silence=SilenceSettings(paragraph_ms=700))
    segs = plan_segments(parse_story("Para one.\n\nPara two."), profile, 400, 0, True)
    assert [s.silence_before_ms for s in segs] == [0, 700]
