"""Pronunciation, preprocessing, cache keys, folder configs, adapter request building."""
import json
import wave
from pathlib import Path

from app.api.audiostudio_adapter import AudioStudioAdapter, DESIGNED_VOICE_SEED
from app.api.errors import TTSError, TTSErrorKind
from app.api.models import VoiceSelection
from app.audio.merger import MergeItem, merge_wavs, wav_duration
from app.core.cache import segment_key
from app.core.folder_config import apply_folder_config, merged_config
from app.core.preprocess import preprocess_text
from app.core.profiles import GenerationProfile
from app.core.pronunciation import PronunciationRule, apply_rules
from app.core.settings import AppSettings, PreprocessOptions


def test_pronunciation_replacement():
    rules = [
        PronunciationRule("WSC", "World Scholar's Cup"),
        PronunciationRule("EC", "E C"),
        PronunciationRule("PECC1", "P E C C One"),
    ]
    out = apply_rules("WSC and EC and PECC1. ECHO stays.", rules)
    assert out == "World Scholar's Cup and E C and P E C C One. ECHO stays."


def test_pronunciation_case_insensitive_and_unicode():
    rules = [PronunciationRule("tp.hcm", "Thành phố Hồ Chí Minh", case_sensitive=False)]
    assert apply_rules("Tôi sống ở TP.HCM.", rules) == "Tôi sống ở Thành phố Hồ Chí Minh."


def test_preprocess_keeps_meaning():
    opts = PreprocessOptions(convert_smart_quotes=True)
    text = "Hello   world.\r\n\r\n\r\n\r\n“Quote”  here."
    assert preprocess_text(text, opts) == 'Hello world.\n\n"Quote" here.'


def test_cache_key_stable_and_sensitive():
    k1 = segment_key("Hello", "profile:a", "", "omnivoice", {"speed": 1.0, "seed": None})
    k2 = segment_key("Hello", "profile:a", "", "omnivoice", {"speed": 1.0})
    assert k1 == k2  # None params ignored
    assert k1 != segment_key("Hello", "profile:b", "", "omnivoice", {"speed": 1.0})
    assert k1 != segment_key("Hello", "profile:a", "", "omnivoice", {"speed": 1.1})
    assert k1 != segment_key("Hello!", "profile:a", "", "omnivoice", {"speed": 1.0})
    assert len(k1) == 64


def test_folder_config_inheritance(tmp_path: Path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "tts_config.json").write_text(json.dumps({"speed": 0.8, "mode": "story"}), encoding="utf-8")
    (tmp_path / "a" / "b" / "tts_config.json").write_text(
        json.dumps({"mode": "conversation", "speaker_voices": {"anna": "profile:x"}}), encoding="utf-8")
    cfg, files = merged_config(tmp_path / "a" / "b", tmp_path, inherit=True)
    assert cfg["mode"] == "conversation" and cfg["speed"] == 0.8 and len(files) == 2
    p = apply_folder_config(GenerationProfile(name="base"), cfg)
    assert p.mode == "conversation" and p.params["speed"] == 0.8
    assert p.speaker_voices["ANNA"].key == "profile:x"
    cfg2, _ = merged_config(tmp_path / "a" / "b", tmp_path, inherit=False)
    assert "speed" not in cfg2


def test_folder_config_stop_inheritance(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "tts_config.json").write_text(json.dumps({"speed": 0.8}), encoding="utf-8")
    (tmp_path / "a" / "tts_config.json").write_text(json.dumps({"inherit_parent": False}), encoding="utf-8")
    cfg, _ = merged_config(tmp_path / "a", tmp_path)
    assert "speed" not in cfg


def _fake_caps_adapter() -> AudioStudioAdapter:
    a = AudioStudioAdapter("http://127.0.0.1:1")
    a._schema = {  # what VoiceStudio 0.5.4 advertises (subset)
        "properties": {
            "input": {"type": "string", "maxLength": 4096},
            "speed": {"type": "number", "minimum": 0.25, "maximum": 4.0, "default": 1.0},
            "instruct": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "seed": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "num_step": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 128}, {"type": "null"}]},
        }
    }
    a._engines = []
    a._engine = lambda model: None  # type: ignore[method-assign]
    return a


def test_capabilities_are_engine_scoped():
    a = _fake_caps_adapter()
    omni = {p.name for p in a.get_capabilities("omnivoice").params}
    kitten = {p.name for p in a.get_capabilities("kittentts").params}
    assert {"speed", "instruct", "seed", "num_step"} <= omni and "description" not in omni
    assert "num_step" not in kitten and "speed" in kitten


def test_build_request_drops_unsupported_and_clamps():
    a = _fake_caps_adapter()
    body = a.build_request("Hi", VoiceSelection("profile:abc", "X"), "kittentts",
                           {"speed": 9, "num_step": 32, "emotion": "happy", "temperature": 0.7})
    assert body["voice"] == "abc" and body["speed"] == 4.0
    assert "num_step" not in body and "emotion" not in body and "temperature" not in body


def test_build_request_designed_voice():
    a = _fake_caps_adapter()
    v = VoiceSelection("archetype:feat_00", "Librarian", "female, middle-aged")
    body = a.build_request("Hi", v, "omnivoice", {"instruct": "calm"})
    assert body["voice"] == "default"
    assert body["instruct"] == "female, middle-aged, calm"
    assert body["seed"] == DESIGNED_VOICE_SEED


def test_oom_detection():
    e = TTSError(TTSErrorKind.SERVER, "CUDA out of memory. Tried to allocate 2 GiB")
    assert e.kind == TTSErrorKind.OUT_OF_MEMORY and not e.retryable


def test_retry_delays_increase():
    s = AppSettings()
    assert [s.retry_delay(i) for i in (1, 2, 3, 4)] == [1.0, 3.0, 5.0, 7.0]


def _tone(path: Path, frames: int, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * frames)


def test_merge_with_silence(tmp_path: Path):
    a, b = tmp_path / "a.wav", tmp_path / "b.wav"
    _tone(a, 24000)
    _tone(b, 12000)
    out = tmp_path / "m.wav"
    dur = merge_wavs([MergeItem(a), MergeItem(b, silence_before_ms=500)], out)
    assert abs(dur - 2.0) < 1e-6 and abs(wav_duration(out) - 2.0) < 1e-6
