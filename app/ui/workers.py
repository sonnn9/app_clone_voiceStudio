"""Run blocking calls off the GUI thread and deliver results back on it."""
from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

log = logging.getLogger("ui.workers")

_alive: set["_Bridge"] = set()


class _Bridge(QObject):
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, on_done: Callable[[Any], None] | None, on_error: Callable[[Exception], None] | None):
        super().__init__()
        self._on_done = on_done
        self._on_error = on_error
        # Receiver is this object (GUI thread) → queued delivery.
        self.done.connect(self._handle_done, Qt.ConnectionType.QueuedConnection)
        self.failed.connect(self._handle_failed, Qt.ConnectionType.QueuedConnection)

    @Slot(object)
    def _handle_done(self, result: Any) -> None:
        try:
            if self._on_done:
                self._on_done(result)
        finally:
            _alive.discard(self)

    @Slot(object)
    def _handle_failed(self, exc: Exception) -> None:
        try:
            if self._on_error:
                self._on_error(exc)
            else:
                log.warning("Background task failed: %s", exc)
        finally:
            _alive.discard(self)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], bridge: _Bridge):
        super().__init__()
        self.fn = fn
        self.bridge = bridge

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # delivered to on_error
            self.bridge.failed.emit(e)
        else:
            self.bridge.done.emit(result)


_pool = QThreadPool()
_pool.setMaxThreadCount(4)


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    bridge = _Bridge(on_done, on_error)
    _alive.add(bridge)
    _pool.start(_Task(fn, bridge))
