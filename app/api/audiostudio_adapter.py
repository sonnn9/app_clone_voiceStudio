"""Adapter for the local AudioStudio (VoiceStudio) REST API.

Every endpoint and field used here was verified against the running server
(see ``docs/API_FINDINGS.md``). When the server's API changes, this is the
only file that needs updating.

Endpoints:
    GET  /health, /system/info, /model/status, /engines/tts
    GET  /profiles, /v1/audio/voices, /archetypes, /openapi.json
    POST /v1/audio/speech                (synthesis, JSON body → audio bytes)
    POST /archetypes/{id}/use            (save a designed voice as a profile)
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable

import httpx

from app.api.base_tts_adapter import BaseTTSAdapter
from app.api.errors import TTSError, TTSErrorKind
from app.api.models import (
    EngineCapabilities,
    EngineInfo,
    HealthInfo,
    ParamSpec,
    VoiceInfo,
    VoiceSelection,
)

log = logging.getLogger("api.audiostudio")

SPEECH_PATH = "/v1/audio/speech"
# Request fields handled explicitly (not shown as generic parameters).
_CORE_FIELDS = {"input", "model", "voice", "response_format"}
# `duration` forces a target length per request – meaningless once text is
# chunked, so it is never exposed for batch generation.
_HIDDEN_FIELDS = {"duration"}

# Seed used for designed (archetype) voices when the profile has none, so the
# same voice identity is reproduced across chunks and files.
DESIGNED_VOICE_SEED = 42


def _is_omnivoice(engine: str) -> bool:
    return engine.startswith("omnivoice") or engine in ("tts-1", "tts-1-hd")


# Engine scoping taken from the SpeechRequest field descriptions.
_ENGINE_SCOPE: dict[str, Callable[[str], bool]] = {
    "description": lambda e: e.startswith("voxcpm"),          # "VoxCPM2 only"
    "num_step": _is_omnivoice,                                 # OmniVoice unmasking steps
    "guidance_scale": _is_omnivoice,                           # OmniVoice CFG
    "denoise": _is_omnivoice,
    "preprocess_prompt": _is_omnivoice,
    "chunk_duration": lambda e: e == "omnivoice-gguf",         # "OmniVoice GGUF extension"
    "chunk_threshold": lambda e: e == "omnivoice-gguf",
}

_LABELS = {
    "speed": "Speed",
    "language": "Language",
    "instruct": "Style instruction",
    "description": "Voice description",
    "seed": "Seed",
    "denoise": "Denoise reference",
    "preprocess_prompt": "Preprocess reference",
    "num_step": "Quality steps",
    "guidance_scale": "Guidance scale (CFG)",
    "chunk_duration": "Internal chunk duration",
    "chunk_threshold": "Internal chunk threshold",
}

# Copy of the SpeechRequest schema observed on VoiceStudio 0.5.4, used only
# when /openapi.json cannot be read.
_FALLBACK_SCHEMA: dict[str, Any] = {
    "properties": {
        "input": {"type": "string", "maxLength": 4096},
        "speed": {"type": "number", "minimum": 0.25, "maximum": 4.0, "default": 1.0},
        "language": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "instruct": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "seed": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "denoise": {"type": "boolean", "default": True},
        "preprocess_prompt": {"type": "boolean", "default": True},
        "num_step": {"anyOf": [{"type": "integer", "minimum": 1, "maximum": 128}, {"type": "null"}]},
        "guidance_scale": {"anyOf": [{"type": "number", "exclusiveMinimum": 0, "maximum": 20}, {"type": "null"}]},
    }
}


class AudioStudioAdapter(BaseTTSAdapter):
    display_name = "AudioStudio (VoiceStudio)"

    def __init__(self, base_url: str = "", timeout_s: float = 300.0) -> None:
        self._base_url = ""
        self._timeout_s = timeout_s
        self._client: httpx.Client | None = None
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        self._schema: dict[str, Any] | None = None
        self._engines: list[EngineInfo] = []
        self._voice_cache: dict[str, tuple[float, list[VoiceInfo]]] = {}
        self._archetypes: list[VoiceInfo] | None = None
        # Avoid hammering an unreachable server with metadata lookups.
        self._meta_failed_at = 0.0
        self.configure(base_url, timeout_s)

    # ------------------------------------------------------------------ setup
    def configure(self, base_url: str, timeout_s: float) -> None:
        url = (base_url or "").strip().rstrip("/")
        with self._lock:
            changed = url != self._base_url
            self._base_url = url
            self._timeout_s = max(5.0, float(timeout_s))
            if changed:
                self._schema = None
                self._engines = []
                self._voice_cache.clear()
                self._archetypes = None
            self._meta_failed_at = 0.0
            self._close_client()

    @property
    def base_url(self) -> str:
        return self._base_url

    def _close_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # pragma: no cover - defensive
                pass
            self._client = None

    def _get_client(self) -> httpx.Client:
        with self._lock:
            if not self._base_url:
                raise TTSError(TTSErrorKind.CONNECTION, "AudioStudio API URL is not set (Settings → API Base URL).")
            if self._client is None:
                self._client = httpx.Client(
                    base_url=self._base_url,
                    timeout=httpx.Timeout(self._timeout_s, connect=5.0),
                    trust_env=False,  # local server: never route through a proxy
                )
            return self._client

    # -------------------------------------------------------------- transport
    def _request(self, method: str, path: str, *, timeout: float | None = None, **kw: Any) -> httpx.Response:
        if self._cancelled.is_set():
            raise TTSError(TTSErrorKind.CANCELLED, "Cancelled")
        client = self._get_client()
        try:
            if timeout is not None:
                kw["timeout"] = httpx.Timeout(timeout, connect=min(5.0, timeout))
            resp = client.request(method, path, **kw)
        except httpx.TimeoutException as e:
            raise TTSError(TTSErrorKind.TIMEOUT, f"No response within the timeout ({e.__class__.__name__}).") from e
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError) as e:
            if self._cancelled.is_set():
                raise TTSError(TTSErrorKind.CANCELLED, "Cancelled") from e
            raise TTSError(TTSErrorKind.CONNECTION, f"Cannot reach {self._base_url}: {e}") from e
        except RuntimeError as e:  # client closed by cancel()
            if self._cancelled.is_set():
                raise TTSError(TTSErrorKind.CANCELLED, "Cancelled") from e
            raise TTSError(TTSErrorKind.UNKNOWN, str(e)) from e
        if resp.status_code >= 400:
            raise self._http_error(resp)
        return resp

    @staticmethod
    def _http_error(resp: httpx.Response) -> TTSError:
        detail: Any
        try:
            detail = resp.json().get("detail", resp.text)
        except (ValueError, AttributeError):
            detail = resp.text
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(
                f"{'.'.join(str(x) for x in d.get('loc', [])[1:])}: {d.get('msg', '')}"
                for d in detail if isinstance(d, dict)
            )
        elif isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail, ensure_ascii=False)
        retry_after = None
        if resp.headers.get("Retry-After"):
            try:
                retry_after = float(resp.headers["Retry-After"])
            except ValueError:
                retry_after = None
        code = resp.status_code
        if code == 429:
            kind = TTSErrorKind.BUSY
        elif code in (400, 404, 409, 413, 422):
            kind = TTSErrorKind.BAD_REQUEST
        elif code in (503, 504):
            kind = TTSErrorKind.BUSY if resp.headers.get("X-OmniVoice-Retryable") else TTSErrorKind.SERVER
        else:
            kind = TTSErrorKind.SERVER
        return TTSError(kind, str(detail), status_code=code, retry_after=retry_after)

    def _get_json(self, path: str, timeout: float = 15.0, **kw: Any) -> Any:
        return self._request("GET", path, timeout=timeout, **kw).json()

    # ----------------------------------------------------------------- health
    def connect(self) -> HealthInfo:
        try:
            data = self._get_json("/health", timeout=5.0)
        except TTSError as e:
            return HealthInfo(connected=False, message=e.human())
        ok = str(data.get("status", "")).lower() == "ok"
        return HealthInfo(
            connected=ok,
            message="Connected" if ok else f"Server reports status '{data.get('status')}'",
            version=str(data.get("version", "")),
            device=str(data.get("device", "")),
        )

    def health_check(self) -> HealthInfo:
        info = self.connect()
        if not info.connected:
            return info
        details: dict[str, Any] = {}
        try:
            sysinfo = self._get_json("/system/info", timeout=10.0)
            info.gpu_name = str(sysinfo.get("gpu_name", ""))
            info.vram_gb = float(sysinfo.get("vram_total_gb") or 0.0)
            info.version = str(sysinfo.get("app_version") or info.version)
            details["Model checkpoint"] = sysinfo.get("model_checkpoint", "")
            details["Server generate timeout (s)"] = sysinfo.get("generate_timeout_s", "")
            details["Server ffmpeg"] = "OK" if sysinfo.get("ffmpeg_ok") else "missing"
            details["Platform"] = sysinfo.get("platform", "")
        except TTSError as e:
            log.debug("system/info unavailable: %s", e)
        try:
            ms = self._get_json("/model/status", timeout=10.0)
            info.model_status = str(ms.get("status", ""))
            if ms.get("checkpoint"):
                details["Loaded checkpoint"] = ms["checkpoint"]
            if ms.get("error"):
                details["Model error"] = ms["error"]
        except TTSError as e:
            log.debug("model/status unavailable: %s", e)
        try:
            eng = self._get_json("/engines/tts", timeout=15.0)
            info.active_engine = str(eng.get("active", ""))
            info.active_model = str(eng.get("active_model", ""))
        except TTSError as e:
            log.debug("engines/tts unavailable: %s", e)
        info.details = {k: v for k, v in details.items() if v not in ("", None)}
        return info

    # ---------------------------------------------------------------- engines
    def get_models(self) -> list[EngineInfo]:
        data = self._get_json("/engines/tts", timeout=20.0)
        active = str(data.get("active", ""))
        engines: list[EngineInfo] = []
        for b in data.get("backends", []):
            engines.append(
                EngineInfo(
                    id=str(b.get("id", "")),
                    name=str(b.get("display_name") or b.get("id", "")),
                    available=bool(b.get("available")),
                    reason=str(b.get("reason") or ""),
                    supports_cloning=bool(b.get("supports_cloning")),
                    supports_emotion=bool(b.get("supports_emotion")),
                    device=str(b.get("effective_device") or ""),
                    is_active=b.get("id") == active,
                )
            )
        self._engines = engines
        return engines

    def _meta_backoff(self) -> bool:
        return time.monotonic() - self._meta_failed_at < 30.0

    def _engine(self, model: str) -> EngineInfo | None:
        if not self._engines and not self._meta_backoff():
            try:
                self.get_models()
            except TTSError:
                self._meta_failed_at = time.monotonic()
                return None
        return next((e for e in self._engines if e.id == model), None)

    # ------------------------------------------------------------ capabilities
    def _speech_schema(self) -> dict[str, Any]:
        if self._schema is None and self._meta_backoff():
            return _FALLBACK_SCHEMA
        if self._schema is None:
            try:
                spec = self._get_json("/openapi.json", timeout=20.0)
                ref = spec["paths"][SPEECH_PATH]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                self._schema = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
            except (TTSError, KeyError, TypeError, ValueError) as e:
                log.warning("Could not read live OpenAPI schema (%s); using built-in copy.", e)
                self._meta_failed_at = time.monotonic()
                return _FALLBACK_SCHEMA
        return self._schema

    @staticmethod
    def _spec_from_property(name: str, prop: dict[str, Any]) -> ParamSpec | None:
        nullable = False
        variants = prop.get("anyOf") or [prop]
        base: dict[str, Any] = {}
        for v in variants:
            if v.get("type") == "null":
                nullable = True
            elif not base:
                base = v
        t = base.get("type")
        kind = {"number": "float", "integer": "int", "boolean": "bool", "string": "str"}.get(t or "")
        if kind is None or "enum" in base:
            return None
        minimum = base.get("minimum", base.get("exclusiveMinimum"))
        return ParamSpec(
            name=name,
            kind=kind,
            label=_LABELS.get(name, prop.get("title") or name),
            default=prop.get("default", base.get("default")),
            minimum=minimum,
            maximum=base.get("maximum"),
            exclusive_minimum="exclusiveMinimum" in base,
            nullable=nullable,
            description=str(prop.get("description") or ""),
        )

    def get_capabilities(self, model: str, offline: bool = False) -> EngineCapabilities:
        schema = (self._schema or _FALLBACK_SCHEMA) if offline else self._speech_schema()
        props: dict[str, Any] = schema.get("properties", {})
        params: list[ParamSpec] = []
        for name, prop in props.items():
            if name in _CORE_FIELDS or name in _HIDDEN_FIELDS:
                continue
            scope = _ENGINE_SCOPE.get(name)
            if scope is not None and not scope(model):
                continue
            spec = self._spec_from_property(name, prop)
            if spec is not None:
                params.append(spec)
        formats = ["wav"]
        rf = props.get("response_format", {})
        if isinstance(rf.get("enum"), list):
            formats = [str(x) for x in rf["enum"]]
        engine = next((e for e in self._engines if e.id == model), None) if offline else self._engine(model)
        return EngineCapabilities(
            engine_id=model,
            params=params,
            max_input_chars=int(props.get("input", {}).get("maxLength") or 4096),
            supports_voice_design=_is_omnivoice(model) and "instruct" in props,
            supports_cloning=bool(engine.supports_cloning) if engine else _is_omnivoice(model),
            supports_emotion=bool(engine.supports_emotion) if engine else False,
            output_formats=formats,
        )

    # ------------------------------------------------------------------ voices
    def get_voices(self, model: str | None = None, refresh: bool = False) -> list[VoiceInfo]:
        model = model or "omnivoice"
        cached = self._voice_cache.get(model)
        if cached and not refresh and time.time() - cached[0] < 600:
            return list(cached[1])
        engine = self._engine(model)
        supports_cloning = engine.supports_cloning if engine else True
        voices: list[VoiceInfo] = [
            VoiceInfo(key="default", name="Engine default", source="default",
                      description="The engine's built-in default voice.")
        ]
        if supports_cloning:
            voices.extend(self._profile_voices())
        if _is_omnivoice(model):
            voices.extend(self._archetype_voices(refresh))
        self._voice_cache[model] = (time.time(), voices)
        return list(voices)

    def _profile_voices(self) -> list[VoiceInfo]:
        try:
            rows = self._get_json("/profiles", timeout=20.0)
        except TTSError as e:
            log.warning("Could not load voice profiles: %s", e)
            # Fall back to the flat OpenAI-style listing.
            try:
                rows = [
                    {"id": v["voice_id"], "name": v.get("name"), "language": v.get("language")}
                    for v in self._get_json("/v1/audio/voices", timeout=20.0).get("voices", [])
                    if v.get("type") == "profile"
                ]
            except TTSError:
                return []
        out: list[VoiceInfo] = []
        for r in rows if isinstance(rows, list) else []:
            instruct = str(r.get("instruct") or "")
            attrs = _parse_vd_states(r.get("vd_states"))
            gender = attrs.get("gender") or _gender_from_text(instruct)
            out.append(
                VoiceInfo(
                    key=f"profile:{r.get('id')}",
                    voice_id=str(r.get("id", "")),
                    name=str(r.get("name") or r.get("id")),
                    source="profile",
                    gender=gender,
                    language=str(r.get("language") or ""),
                    age=attrs.get("age", ""),
                    pitch=attrs.get("pitch", ""),
                    accent=attrs.get("accent", ""),
                    style="My voices" if not r.get("is_demo") else "Demo",
                    description=str(r.get("description") or ""),
                    instruct="",  # the server applies the profile's own instruct
                    kind=str(r.get("kind") or ""),
                )
            )
        return out

    def _archetype_voices(self, refresh: bool) -> list[VoiceInfo]:
        if self._archetypes is not None and not refresh:
            return self._archetypes
        items: list[dict[str, Any]] = []
        offset, limit = 0, 500  # server maximum page size is 500
        try:
            while True:
                page = self._get_json("/archetypes", timeout=30.0, params={"limit": limit, "offset": offset})
                batch = page.get("items", []) if isinstance(page, dict) else []
                items.extend(batch)
                total = int(page.get("total", len(items))) if isinstance(page, dict) else len(items)
                offset += len(batch)
                if not batch or offset >= total:
                    break
        except TTSError as e:
            log.warning("Could not load designed voices: %s", e)
        out: list[VoiceInfo] = []
        for a in items:
            facets = a.get("facets") or {}
            out.append(
                VoiceInfo(
                    key=f"archetype:{a.get('id')}",
                    voice_id=str(a.get("id", "")),
                    name=str(a.get("name") or a.get("id")),
                    source="archetype",
                    gender=str(facets.get("gender") or "").capitalize(),
                    language=str(a.get("language") or facets.get("lang") or ""),
                    accent=str(facets.get("accent") or ""),
                    age=str(facets.get("age") or ""),
                    pitch=str(facets.get("pitch") or ""),
                    style=str(a.get("use_case") or ""),
                    description=str(a.get("sample_script") or ""),
                    instruct=str(a.get("instruct") or ""),
                    kind="design",
                )
            )
        self._archetypes = out
        return out

    def save_archetype_as_profile(self, archetype_id: str, name: str | None = None) -> dict[str, Any]:
        """Materialise a designed voice into a reusable server-side profile."""
        params = {"name": name} if name else None
        resp = self._request("POST", f"/archetypes/{archetype_id}/use", params=params, timeout=self._timeout_s)
        self._voice_cache.clear()
        return resp.json()

    # -------------------------------------------------------------- synthesis
    def build_request(
        self,
        text: str,
        voice: VoiceSelection,
        model: str,
        parameters: dict[str, Any],
        response_format: str = "wav",
    ) -> dict[str, Any]:
        """Build the JSON body, dropping anything the engine does not support."""
        caps = self.get_capabilities(model)
        body: dict[str, Any] = {"model": model, "input": text, "response_format": response_format}
        for name, value in parameters.items():
            spec = caps.param(name)
            if spec is None or value is None or (isinstance(value, str) and not value.strip()):
                continue
            body[name] = spec.clamp(value)

        key = voice.key or "default"
        if key.startswith("profile:"):
            body["voice"] = key.split(":", 1)[1]
        elif key.startswith("archetype:"):
            # Designed voice: identity comes from its instruct prompt.
            body["voice"] = "default"
            style = str(body.get("instruct") or "").strip()
            design = voice.instruct.strip()
            if design and caps.supports("instruct"):
                body["instruct"] = f"{design}, {style}" if style else design
            if caps.supports("seed") and body.get("seed") is None:
                body["seed"] = DESIGNED_VOICE_SEED
        elif key.startswith("alias:"):
            body["voice"] = key.split(":", 1)[1]
        else:
            body["voice"] = key if key != "default" else "default"
        return body

    def generate(
        self,
        text: str,
        voice: VoiceSelection,
        model: str,
        parameters: dict[str, Any],
        response_format: str = "wav",
    ) -> bytes:
        body = self.build_request(text, voice, model, parameters, response_format)
        log.info(
            "POST %s model=%s voice=%s chars=%d params=%s",
            SPEECH_PATH, model, body.get("voice"), len(text),
            {k: v for k, v in body.items() if k not in ("input",)},
        )
        resp = self._request("POST", SPEECH_PATH, json=body, timeout=self._timeout_s)
        ctype = resp.headers.get("content-type", "")
        if not ctype.startswith("audio/"):
            raise TTSError(TTSErrorKind.SERVER, f"Unexpected response type '{ctype}'.", status_code=resp.status_code)
        data = resp.content
        if response_format == "wav" and not data.startswith(b"RIFF"):
            raise TTSError(TTSErrorKind.SERVER, "Server did not return WAV audio.")
        return data

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            self._close_client()

    def reset_cancel(self) -> None:
        self._cancelled.clear()

    def default_language_suggestions(self) -> list[str]:
        # ISO 639-1 codes accepted by the `language` field; empty = auto.
        return ["", "en", "vi", "zh", "ja", "ko", "fr", "de", "es", "it", "pt", "ru", "th", "id"]


def _gender_from_text(text: str) -> str:
    low = f" {text.lower()} "
    if " female" in low or "woman" in low:
        return "Female"
    if " male" in low or " man " in low:
        return "Male"
    return ""


def _parse_vd_states(raw: Any) -> dict[str, str]:
    """Extract Gender/Age/Pitch/Accent from a designed profile's vd_states."""
    if not raw:
        return {}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for src, dst in (("Gender", "gender"), ("Age", "age"), ("Pitch", "pitch"), ("EnglishAccent", "accent")):
        v = data.get(src)
        if isinstance(v, str) and v and v.lower() != "auto":
            out[dst] = v.capitalize() if dst == "gender" else v
    return out
