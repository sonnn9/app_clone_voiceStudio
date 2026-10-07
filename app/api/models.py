"""Engine-neutral data classes exchanged between adapters and the app."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EngineInfo:
    id: str
    name: str
    available: bool = True
    reason: str = ""
    supports_cloning: bool = False
    supports_emotion: bool = False
    device: str = ""
    is_active: bool = False

    @property
    def label(self) -> str:
        return self.name or self.id


@dataclass
class VoiceInfo:
    """A voice offered by the backend. ``key`` is the stable identifier."""

    key: str
    name: str
    source: str  # "profile" | "archetype" | "alias" | "default"
    voice_id: str = ""
    gender: str = ""
    language: str = ""
    accent: str = ""
    age: str = ""
    pitch: str = ""
    style: str = ""  # use-case / category
    description: str = ""
    instruct: str = ""
    kind: str = ""  # clone / design for profiles

    def selection(self) -> "VoiceSelection":
        return VoiceSelection(key=self.key, name=self.name, instruct=self.instruct)

    def matches(self, query: str) -> bool:
        q = query.casefold()
        hay = " ".join(
            [self.name, self.voice_id, self.language, self.accent, self.style,
             self.description, self.instruct, self.gender, self.age]
        ).casefold()
        return q in hay


@dataclass
class VoiceSelection:
    """What a profile stores for a voice: enough to generate even offline."""

    key: str = "default"
    name: str = "Engine default"
    instruct: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_any(cls, value: Any) -> "VoiceSelection":
        if isinstance(value, VoiceSelection):
            return value
        if isinstance(value, dict):
            return cls(
                key=str(value.get("key") or "default"),
                name=str(value.get("name") or value.get("key") or "Engine default"),
                instruct=str(value.get("instruct") or ""),
            )
        if isinstance(value, str) and value.strip():
            v = value.strip()
            return cls(key=v, name=v.split(":", 1)[-1])
        return cls()

    @property
    def is_default(self) -> bool:
        return self.key in ("", "default")


@dataclass
class ParamSpec:
    """One generation parameter as advertised by the backend schema."""

    name: str
    kind: str  # "float" | "int" | "bool" | "str"
    label: str = ""
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    nullable: bool = True
    description: str = ""

    def clamp(self, value: Any) -> Any:
        if value is None:
            return None
        try:
            if self.kind == "int":
                value = int(value)
            elif self.kind == "float":
                value = float(value)
            elif self.kind == "bool":
                return bool(value)
            else:
                return str(value)
        except (TypeError, ValueError):
            return self.default
        if self.minimum is not None:
            if self.exclusive_minimum and value <= self.minimum:
                value = self.default if self.default is not None else type(value)(self.minimum + (1 if self.kind == "int" else 0.1))
            elif value < self.minimum:
                value = type(value)(self.minimum)
        if self.maximum is not None and value > self.maximum:
            value = type(value)(self.maximum)
        return value


@dataclass
class EngineCapabilities:
    engine_id: str
    params: list[ParamSpec] = field(default_factory=list)
    max_input_chars: int = 4096
    supports_voice_design: bool = False
    supports_cloning: bool = False
    supports_emotion: bool = False
    output_formats: list[str] = field(default_factory=lambda: ["wav"])

    def param(self, name: str) -> ParamSpec | None:
        return next((p for p in self.params if p.name == name), None)

    def supports(self, name: str) -> bool:
        return self.param(name) is not None


@dataclass
class HealthInfo:
    connected: bool
    message: str = ""
    version: str = ""
    device: str = ""
    gpu_name: str = ""
    vram_gb: float = 0.0
    model_status: str = ""
    active_engine: str = ""
    active_model: str = ""
    details: dict[str, Any] = field(default_factory=dict)
