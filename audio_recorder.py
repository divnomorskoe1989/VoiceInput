from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable, Iterator

try:
    import numpy as np
except ImportError:  # pragma: no cover - optional runtime dependency
    np = None  # type: ignore[assignment]

try:
    import sounddevice as sd
except ImportError:  # pragma: no cover - optional runtime dependency
    sd = None  # type: ignore[assignment]


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_size: int = 1024,
        ring_buffer_chunks: int = 256,
        silence_timeout_sec: float = 5.0,
        silence_rms_threshold: float = 500.0,
        microphone_enabled: bool = False,
        microphone_device: str = "",
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.ring_buffer_chunks = ring_buffer_chunks
        self.silence_timeout_sec = silence_timeout_sec
        self.silence_rms_threshold = silence_rms_threshold
        self.microphone_enabled = microphone_enabled
        self.microphone_device = microphone_device or None
        self._time_fn = time_fn or time.monotonic
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=ring_buffer_chunks)
        self._running = False
        self._auto_stop_callback: Callable[[], None] | None = None
        self._last_voice_ts = self._time_fn()
        self._auto_stop_inflight = False
        self._auto_stop_lock = threading.Lock()
        self._input_stream: Any | None = None
        self._session_started_ts = self._time_fn()
        self._session_chunks_total = 0
        self._session_voice_chunks = 0
        self._session_silence_chunks = 0
        self._session_rms_sum = 0.0
        self._session_rms_count = 0
        self._session_rms_max = 0.0
        self._logger = logging.getLogger("AudioRecorder")

    @property
    def is_running(self) -> bool:
        return self._running

    def set_auto_stop_callback(self, callback: Callable[[], None]) -> None:
        self._auto_stop_callback = callback

    def _reset_session_metrics(self) -> None:
        self._session_started_ts = self._time_fn()
        self._session_chunks_total = 0
        self._session_voice_chunks = 0
        self._session_silence_chunks = 0
        self._session_rms_sum = 0.0
        self._session_rms_count = 0
        self._session_rms_max = 0.0

    def start(self) -> None:
        self._running = True
        self._reset_session_metrics()
        self._last_voice_ts = self._time_fn()
        self._auto_stop_inflight = False
        self._logger.debug(
            "Recorder started: rate=%s chunk=%s buffer=%s silence_timeout=%ss threshold=%s",
            self.sample_rate,
            self.chunk_size,
            self.ring_buffer_chunks,
            self.silence_timeout_sec,
            self.silence_rms_threshold,
        )
        if self.microphone_enabled:
            self._start_microphone_stream()

    def stop(self) -> None:
        self._running = False
        self._stop_microphone_stream()
        session_duration_sec = max(0.0, self._time_fn() - self._session_started_ts)
        rms_avg = (
            self._session_rms_sum / self._session_rms_count
            if self._session_rms_count > 0
            else 0.0
        )
        voiced_pct = (
            (self._session_voice_chunks / self._session_chunks_total) * 100.0
            if self._session_chunks_total > 0
            else 0.0
        )
        self._logger.info(
            "MIC | event=session_stats | duration_sec=%.3f | chunks=%s | voiced_chunks=%s | silence_chunks=%s | voiced_pct=%.1f | rms_avg=%.1f | rms_max=%.1f | threshold=%.1f",
            session_duration_sec,
            self._session_chunks_total,
            self._session_voice_chunks,
            self._session_silence_chunks,
            voiced_pct,
            rms_avg,
            self._session_rms_max,
            self.silence_rms_threshold,
        )
        self._logger.debug("Recorder stopped.")

    def _on_input_chunk(self, indata: Any, frames: int, callback_time: Any, status: Any) -> None:
        del frames, callback_time
        if status:
            self._logger.warning("Microphone callback status: %s", status)
        if not self._running:
            return

        try:
            chunk = indata.tobytes()
        except Exception:
            self._logger.exception("Failed to convert audio chunk to bytes.")
            return

        rms: float | None = None
        if np is not None:
            try:
                rms = float(np.sqrt(np.mean(np.square(indata.astype("float32")))))
            except Exception:
                self._logger.exception("Failed to calculate chunk RMS.")

        self.push_chunk(chunk, rms=rms)

    def _start_microphone_stream(self) -> None:
        if sd is None:
            raise RuntimeError(
                "Microphone mode requested, but sounddevice is not installed. "
                "Install dependencies from requirements.txt."
            )
        if self._input_stream is not None:
            return

        started = time.perf_counter()
        self._input_stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            channels=1,
            dtype="int16",
            callback=self._on_input_chunk,
            device=self.microphone_device,
        )
        self._input_stream.start()
        self._logger.info(
            "MIC | event=started | sample_rate=%s | chunk_size=%s | device=%s | latency_ms=%.1f",
            self.sample_rate,
            self.chunk_size,
            self.microphone_device or "default",
            (time.perf_counter() - started) * 1000,
        )

    def _stop_microphone_stream(self) -> None:
        if self._input_stream is None:
            return
        started = time.perf_counter()
        try:
            self._input_stream.stop()
            self._input_stream.close()
        finally:
            self._input_stream = None
        self._logger.info("MIC | event=stopped | latency_ms=%.1f", (time.perf_counter() - started) * 1000)

    def _schedule_auto_stop(self) -> None:
        if self._auto_stop_callback is None:
            return

        with self._auto_stop_lock:
            if self._auto_stop_inflight:
                return
            self._auto_stop_inflight = True

        def run_callback() -> None:
            try:
                self._auto_stop_callback()
            finally:
                with self._auto_stop_lock:
                    self._auto_stop_inflight = False

        threading.Thread(target=run_callback, daemon=True).start()

    def push_chunk(self, chunk: bytes, rms: float | None = None) -> None:
        if not self._running:
            return
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            self._logger.warning("Audio ring buffer is full; dropping chunk.")

        if rms is None:
            rms = 1000.0

        self._session_chunks_total += 1
        self._session_rms_sum += rms
        self._session_rms_count += 1
        if rms > self._session_rms_max:
            self._session_rms_max = rms

        now = self._time_fn()
        if rms > self.silence_rms_threshold:
            self._session_voice_chunks += 1
            self._last_voice_ts = now
            return

        self._session_silence_chunks += 1
        elapsed = now - self._last_voice_ts
        if elapsed >= self.silence_timeout_sec and self._auto_stop_callback is not None:
            self._logger.info(
                "Silence detected for %.1fs (rms=%.1f <= %.1f); triggering auto-stop.",
                elapsed,
                rms,
                self.silence_rms_threshold,
            )
            self._schedule_auto_stop()

    def iter_chunks(self) -> Iterator[bytes]:
        while self._running or not self._queue.empty():
            try:
                yield self._queue.get(timeout=0.05)
            except queue.Empty:
                if not self._running:
                    return
