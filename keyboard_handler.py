from __future__ import annotations

import logging
import sys
import time
from typing import Callable


class HotkeyHandler:
    def __init__(
        self,
        hotkey: str = "ctrl+win",
        debounce_ms: int = 220,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.hotkey = hotkey
        self.debounce_ms = max(0, int(debounce_ms))
        self._time_fn = time_fn or time.monotonic
        self._callback: Callable[[], None] | None = None
        self._logger = logging.getLogger("HotkeyHandler")
        self._last_trigger_ts = 0.0

    def set_callback(self, callback: Callable[[], None]) -> None:
        self._callback = callback

    def trigger(self) -> bool:
        now = self._time_fn()
        delta_ms = (now - self._last_trigger_ts) * 1000 if self._last_trigger_ts else None

        if delta_ms is not None and delta_ms < self.debounce_ms:
            self._logger.warning(
                "HOTKEY | event=ignored_debounce | hotkey=%s | delta_ms=%.1f | debounce_ms=%s",
                self.hotkey,
                delta_ms,
                self.debounce_ms,
            )
            return False

        self._last_trigger_ts = now
        self._logger.info(
            "HOTKEY | event=accepted | hotkey=%s | delta_ms=%s | debounce_ms=%s",
            self.hotkey,
            "n/a" if delta_ms is None else f"{delta_ms:.1f}",
            self.debounce_ms,
        )

        if self._callback is None:
            self._logger.warning("HOTKEY | event=no_callback | hotkey=%s", self.hotkey)
            return False

        started = time.perf_counter()
        try:
            self._callback()
        except Exception as exc:
            self._logger.exception(
                "HOTKEY | event=callback_failed | hotkey=%s | error=%r",
                self.hotkey,
                exc,
            )
            print(f"[VoiceInput] Hotkey action failed: {exc}", file=sys.stderr)
            return False
        self._logger.info(
            "HOTKEY | event=callback_completed | hotkey=%s | callback_latency_ms=%.1f",
            self.hotkey,
            (time.perf_counter() - started) * 1000,
        )
        return True
