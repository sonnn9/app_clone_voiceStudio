# Phase 1 – AudioStudio (VoiceStudio) local API findings

Inspected on 2026-10-07 against the locally running backend
(`VoiceStudio API` **0.5.4**, source in `D:\Project\VoiceStudio\backend`),
using its live `/openapi.json`, its router source code
(`api/routers/openai_compat.py`) and real requests.

> The "AudioStudio" server referred to in the requirements is the local
> **VoiceStudio** backend (FastAPI/uvicorn). Everything below was verified
> against the real server – nothing is assumed.

## Base URL

* The backend prints/uses `backend_port` (reported by `GET /system/info`).
  On this machine it listens on `http://127.0.0.1:3900` (VoiceStudio's
  documented default). The app never hard-codes this: the URL is a user
  setting; *Detect* only tries the candidate list in `default_settings.json`.
* No authentication is required for local requests (`/v1/audio/capabilities`
  → `authentication`).

## Endpoints used by the app

| Purpose | Endpoint | Notes |
|---|---|---|
| Health | `GET /health` | `{"status":"ok","device":"cuda (NVIDIA GeForce RTX 3060)","version":"0.5.4"}` |
| System / GPU | `GET /system/info` | `app_version, device, gpu_name, vram_total_gb, model_checkpoint, generate_timeout_s, backend_port, ffmpeg_ok …` |
| Model state | `GET /model/status` | `status: idle|loading|ready, checkpoint, sub_stage, error` |
| Engines ("models") | `GET /engines/tts` | `active, active_model, backends[]` with `id, display_name, available, reason, supports_cloning, supports_emotion, effective_device, min_vram_gb …` |
| Voices (flat) | `GET /v1/audio/voices` | `voices[]` = OpenAI aliases + saved voice profiles (`voice_id, name, type, language`) |
| Voice profiles (rich) | `GET /profiles` | `id, name, language, instruct, description, kind (clone/design), seed, is_demo …` |
| Designed voices | `GET /archetypes?limit≤500&offset=` | 1 126 catalog voices with `facets: gender, age, pitch, accent, lang`, `use_case`, `instruct` |
| Archetype categories | `GET /archetypes/categories` | 7 use-case categories |
| Materialise archetype | `POST /archetypes/{id}/use?name=` | creates a reusable voice profile (user-triggered only) |
| **Generate** | `POST /v1/audio/speech` | JSON body (below), returns raw audio bytes |
| OpenAPI | `GET /openapi.json` | used at runtime to read the *actual* request schema |

## Generation request – `POST /v1/audio/speech` (`SpeechRequest`)

| Field | Type / limits | Meaning (from schema + source) |
|---|---|---|
| `input` | string, **maxLength 4096**, required | text |
| `model` | string, default `omnivoice` | engine id (`omnivoice`, `kittentts`, …) or `tts-1`/`tts-1-hd` = active engine |
| `voice` | string, default `default` | voice **profile id**, `default`, an OpenAI alias, or an engine preset name |
| `response_format` | `mp3|opus|aac|flac|wav|pcm` | server MP3 is 24 kHz **64 kbps mono** → app requests `wav` and encodes MP3 locally |
| `speed` | 0.25 – 4.0 | |
| `language` | ISO-639-1 or null | |
| `instruct` | string | style instruction; for OmniVoice it is the voice-design prompt (`"female, young adult, moderate pitch"`) |
| `description` | string | VoxCPM2 only |
| `duration` | > 0 | target duration (s) |
| `seed` | int | deterministic sampling |
| `denoise`, `preprocess_prompt` | bool | OmniVoice extensions |
| `num_step` | 1 – 128 | OmniVoice unmasking steps |
| `guidance_scale` | (0, 20] | OmniVoice CFG |
| `chunk_duration`, `chunk_threshold` | ≥ 0 | OmniVoice GGUF only |

Voice resolution in the server: a profile id → its reference audio,
`ref_text`, `instruct`, `seed`. Archetypes are **not** profile ids; they are
used by sending `voice:"default"` + the archetype's `instruct` (+ a fixed
seed for a stable identity) – verified with a real request.

### Responses / errors (verified)

* `200` – audio bytes, `content-type: audio/wav` (or `audio/mpeg`).
* `400` – `{"detail": "Unknown model 'x' …"}`, bad input, engine unavailable.
* `422` – schema validation (`detail` is a list).
* `429` – GPU pool saturated, `Retry-After` + `X-OmniVoice-Retryable: true`.
* `503` – engine still loading / timeout, `Retry-After`.
* `500` – generic engine failure (CUDA OOM text appears in `detail`).

### Not available in the API

* No per-request cancel for `/v1/audio/speech` (`/tasks/cancel` is only for
  background tasks) → the app cancels by closing the HTTP request.
* No streaming for this endpoint.
* No dedicated emotion/pitch/volume/temperature/exaggeration/CFG fields
  (except OmniVoice `guidance_scale`). Those controls are **not shown**.
* No gender metadata on saved profiles (only on archetypes).
* KittenTTS preset names are not listed by any endpoint → not offered.

## Capability rules implemented

* Parameters shown in the UI come from the live `SpeechRequest` schema,
  filtered per engine (`description` → voxcpm2, `num_step/guidance_scale/
  denoise/preprocess_prompt` → OmniVoice family, `chunk_*` → omnivoice-gguf).
* Archetype voices are offered only for OmniVoice-family engines; profile
  (cloned) voices only for engines with `supports_cloning`.
* Max chunk size is capped by `input.maxLength`.

## Architecture summary

```
UI (PySide6 pages) ──signals──► BatchManager (QObject, thread pool)
                                   │  per job
                                   ▼
                     JobProcessor (pure Python)
          read TXT → preprocess → parse (Story/Conversation parser)
          → split chunks → segments → TTS adapter (cache, retries)
          → merge WAV + silences → convert (ffmpeg) → atomic rename
                                   │
                         BaseTTSAdapter ◄── AudioStudioAdapter (httpx)
```

Data model: `AppSettings`, `GenerationProfile` (engine, voice, speaker
voices, params, pauses, pronunciation rules), `VoiceInfo`, `VoiceSelection`,
`Job` (status, progress, output, error, timings), `BatchSession` (persisted
queue). Details in `README.md`.
