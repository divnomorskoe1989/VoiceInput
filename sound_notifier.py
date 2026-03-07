from __future__ import annotations

import atexit
import logging
import queue
import threading
from contextlib import suppress
from typing import Callable

try:
    import winsound
except ImportError:  # pragma: no cover - non-Windows fallback
    winsound = None  # type: ignore[assignment]


class SoundNotifier:
    def __init__(self, callback: Callable[..., None] | None = None, enabled: bool = True) -> None:
        self._callback = callback
        self._enabled = enabled
        self._logger = logging.getLogger("SoundNotifier")
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._closed = False
        self._close_lock = threading.Lock()
        atexit.register(self.close)

    def _log(self, level: int, message: str, *args: object) -> None:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            stream = getattr(handler, "stream", None)
            if stream is not None and getattr(stream, "closed", False):
                root_logger.removeHandler(handler)
                with suppress(Exception):
                    handler.close()
        self._logger.log(level, message, *args)

    def _run_callback(self, signal_type: str) -> None:
        if self._callback is None:
            return
        try:
            self._callback(signal_type)
        except TypeError:
            self._callback()

    def _play_tones(self, signal_type: str) -> None:
        if winsound is None:
            self._log(logging.DEBUG, "winsound is unavailable; skipping sound playback.")
            return

        if signal_type == "start":
            sequence = [(880, 90), (1100, 90)]
        else:
            sequence = [(660, 120), (440, 140)]

        self._log(logging.INFO, "SOUND | event=play_started | signal=%s", signal_type)
        for index, (frequency, duration_ms) in enumerate(sequence, start=1):
            self._log(
                logging.DEBUG,
                "SOUND | event=tone | signal=%s | tone_index=%s | frequency=%s | duration_ms=%s",
                signal_type,
                index,
                frequency,
                duration_ms,
            )
            try:
                winsound.Beep(frequency, duration_ms)
            except RuntimeError:
                self._log(
                    logging.ERROR,
                    "SOUND | event=play_error | frequency=%s | duration_ms=%s",
                    frequency,
                    duration_ms,
                )
        self._log(logging.INFO, "SOUND | event=play_finished | signal=%s", signal_type)

    def _worker_loop(self) -> None:
        while True:
            signal_type = self._queue.get()
            try:
                if signal_type is None:
                    return
                self._play_tones(signal_type)
            finally:
                self._queue.task_done()

    def _ensure_worker(self) -> None:
        with self._worker_lock:
            if self._closed:
                return
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()
            self._log(logging.INFO, "SOUND | event=worker_started")

    def _notify(self, signal_type: str) -> None:
        if self._closed:
            return
        self._log(logging.INFO, "SOUND | event=requested | signal=%s", signal_type)
        self._run_callback(signal_type)

        if not self._enabled:
            self._log(logging.INFO, "SOUND | event=disabled | signal=%s", signal_type)
            return

        self._ensure_worker()
        self._queue.put(signal_type)
        self._log(
            logging.INFO,
            "SOUND | event=queued | signal=%s | queue_size=%s",
            signal_type,
            self._queue.qsize(),
        )

    def notify_start(self) -> None:
        self._notify("start")

    def notify_stop(self) -> None:
        self._notify("stop")

    def notify(self) -> None:
        # Backward-compatible alias for the old single notification event.
        self.notify_start()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        with self._worker_lock:
            worker = self._worker
            if worker is None:
                return
            self._queue.put(None)
        worker.join(timeout=1.0)
