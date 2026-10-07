"""Human-readable, classified TTS errors."""
from __future__ import annotations

from enum import Enum


class TTSErrorKind(str, Enum):
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    OUT_OF_MEMORY = "out_of_memory"
    BAD_REQUEST = "bad_request"
    BUSY = "busy"
    SERVER = "server"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


_RETRYABLE = {
    TTSErrorKind.CONNECTION,
    TTSErrorKind.TIMEOUT,
    TTSErrorKind.BUSY,
    TTSErrorKind.SERVER,
    TTSErrorKind.UNKNOWN,
}

_OOM_MARKERS = (
    "out of memory",
    "outofmemoryerror",
    "cuda oom",
    "cudnn_status_alloc_failed",
    "cublas_status_alloc_failed",
    "not enough memory",
)

HINTS = {
    TTSErrorKind.CONNECTION: "AudioStudio is not reachable. Make sure the AudioStudio app/server is running "
                             "and the API URL in Settings is correct.",
    TTSErrorKind.TIMEOUT: "The server took too long. Increase the timeout in Settings, use shorter chunks, "
                          "or check that the model finished loading.",
    TTSErrorKind.OUT_OF_MEMORY: "GPU memory is exhausted. Decrease Concurrent Jobs to 1, restart the TTS backend, "
                                "or use shorter chunks (Settings → Max characters per chunk).",
    TTSErrorKind.BUSY: "The GPU queue is full. The job will be retried automatically.",
    TTSErrorKind.BAD_REQUEST: "The server rejected the request. Check the selected engine/voice and parameters.",
    TTSErrorKind.SERVER: "The TTS engine reported an internal error.",
    TTSErrorKind.CANCELLED: "Cancelled by user.",
    TTSErrorKind.UNKNOWN: "Unexpected error.",
}


def is_oom_message(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _OOM_MARKERS)


class TTSError(Exception):
    def __init__(
        self,
        kind: TTSErrorKind,
        message: str,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        if kind not in (TTSErrorKind.OUT_OF_MEMORY, TTSErrorKind.CANCELLED) and is_oom_message(message):
            kind = TTSErrorKind.OUT_OF_MEMORY
        self.kind = kind
        self.message = message
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(self.human())

    @property
    def retryable(self) -> bool:
        return self.kind in _RETRYABLE

    @property
    def hint(self) -> str:
        return HINTS.get(self.kind, "")

    def human(self) -> str:
        label = {
            TTSErrorKind.CONNECTION: "Server unavailable",
            TTSErrorKind.TIMEOUT: "Timeout",
            TTSErrorKind.OUT_OF_MEMORY: "GPU out of memory",
            TTSErrorKind.BAD_REQUEST: "Request rejected",
            TTSErrorKind.BUSY: "Server busy",
            TTSErrorKind.SERVER: "Server error",
            TTSErrorKind.CANCELLED: "Cancelled",
            TTSErrorKind.UNKNOWN: "Error",
        }[self.kind]
        code = f" (HTTP {self.status_code})" if self.status_code else ""
        msg = (self.message or "").strip()
        if len(msg) > 400:
            msg = msg[:400] + "…"
        return f"{label}{code}: {msg}" if msg else f"{label}{code}"
