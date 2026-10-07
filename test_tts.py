"""Phase-2 CLI check of the AudioStudio adapter (no GUI).

    python test_tts.py --url http://127.0.0.1:3900
    python test_tts.py --url http://127.0.0.1:3900 --voice profile:demo0001 --text "Xin chào"
    python test_tts.py --url http://127.0.0.1:3900 --list-voices

Writes ``test_output.mp3`` (or ``.wav`` when ffmpeg is missing).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from app.api.audiostudio_adapter import AudioStudioAdapter
from app.api.errors import TTSError
from app.api.models import VoiceSelection
from app.audio.converter import encode_audio
from app.audio.ffmpeg import find_ffmpeg
from app.core.settings import load_settings


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = load_settings()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=settings.api_base_url, help="AudioStudio API base URL")
    ap.add_argument("--model", default="omnivoice", help="engine id (see --list-models)")
    ap.add_argument("--voice", default="default", help="voice key, e.g. profile:<id> or archetype:<id>")
    ap.add_argument("--text", default="Hello. This is a voice preview.")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--out", default="test_output.mp3")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()
    if not args.url:
        print("Set --url (e.g. http://127.0.0.1:<port>) or configure it in the app.")
        return 2

    adapter = AudioStudioAdapter(args.url, timeout_s=settings.timeout_s)
    health = adapter.health_check()
    print(f"Connected: {health.connected}  {health.message}")
    if not health.connected:
        return 1
    print(f"Version {health.version} | device {health.device} | GPU {health.gpu_name} {health.vram_gb:.1f} GB "
          f"| model status {health.model_status} | active engine {health.active_engine}")

    if args.list_models:
        for e in adapter.get_models():
            print(f"  {'*' if e.is_active else ' '} {e.id:22} available={e.available} cloning={e.supports_cloning} "
                  f"emotion={e.supports_emotion}  {e.name}")
    caps = adapter.get_capabilities(args.model)
    print(f"Parameters for {args.model}: {', '.join(p.name for p in caps.params)} (max {caps.max_input_chars} chars)")

    voices = adapter.get_voices(args.model)
    print(f"{len(voices)} voices available for {args.model}")
    if args.list_voices:
        for v in voices:
            print(f"  {v.key:45} {v.name:35} {v.gender:7} {v.language:10} {v.accent:18} {v.style}")

    selected = next((v.selection() for v in voices if v.key == args.voice), VoiceSelection.from_any(args.voice))
    print(f"Generating with voice '{selected.name}' …")
    try:
        wav = adapter.generate(args.text, selected, args.model, {"speed": args.speed})
    except TTSError as e:
        print(f"FAILED: {e.human()}\n{e.hint}")
        return 1
    out = Path(args.out)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "speech.wav"
        src.write_bytes(wav)
        ffmpeg = find_ffmpeg(settings.ffmpeg_path)
        if out.suffix.lower() == ".mp3" and not ffmpeg:
            out = out.with_suffix(".wav")
            print("ffmpeg not found – writing WAV instead.")
        encode_audio(src, out, out.suffix.lstrip(".").lower(), ffmpeg, settings.mp3_bitrate_kbps)
    print(f"OK → {out.resolve()} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
