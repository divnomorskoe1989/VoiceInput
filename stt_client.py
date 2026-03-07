from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import suppress
from collections import deque
from typing import Deque, Iterable, Iterator
from urllib.parse import urlencode

try:
    from websockets.exceptions import ConnectionClosed
    from websockets.sync.client import connect as ws_connect
except ImportError:  # pragma: no cover - optional runtime dependency
    ConnectionClosed = Exception  # type: ignore[assignment]
    ws_connect = None  # type: ignore[assignment]

from contracts import TranscriptEvent


class STTClient:
    def connect(self) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def stream_transcripts(self, audio_chunks: Iterable[bytes]) -> Iterator[TranscriptEvent]:
        raise NotImplementedError


class MockSTTClient(STTClient):
    def __init__(self) -> None:
        self._logger = logging.getLogger("STTClient")
        self._connected = False
        self._queued_events: Deque[TranscriptEvent] = deque()
        self._default_final_text = "recovered voice input"

    def set_default_final_text(self, text: str) -> None:
        self._default_final_text = text

    def queue_event(self, text: str, is_final: bool) -> None:
        self._queued_events.append(TranscriptEvent(text=text, is_final=is_final))

    def connect(self) -> bool:
        started = time.perf_counter()
        self._connected = True
        self._logger.debug("STT connect took %.3fs, success=True", time.perf_counter() - started)
        return True

    def close(self) -> None:
        self._connected = False
        self._logger.debug("STT connection closed in 0.000s.")

    def stream_transcripts(self, audio_chunks: Iterable[bytes]) -> Iterator[TranscriptEvent]:
        chunk_count = 0
        for _ in audio_chunks:
            chunk_count += 1
            if chunk_count and chunk_count % 50 == 0:
                self._logger.debug("Sent %s audio chunks to STT.", chunk_count)

        if self._queued_events:
            while self._queued_events:
                yield self._queued_events.popleft()
            return

        if chunk_count:
            yield TranscriptEvent(text=self._default_final_text, is_final=True)


class DeepgramSTTClient(MockSTTClient):
    """Deepgram websocket client with recovery-compatible fallback behaviour."""

    def __init__(
        self,
        api_key: str,
        model: str = "nova-2",
        language: str = "ru",
        interim_results: bool = True,
        smart_format: bool = True,
        sample_rate: int = 16000,
        endpointing_ms: int = 400,
    ) -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._language = language
        self._interim_results = interim_results
        self._smart_format = smart_format
        self._sample_rate = sample_rate
        self._endpointing_ms = endpointing_ms
        self._logger = logging.getLogger("STTClient")
        self._stop_event = threading.Event()
        self._connection_lock = threading.Lock()
        self._connection = None

    def connect(self) -> bool:
        if not self._api_key:
            raise ValueError("DEEPGRAM_API_KEY is required")
        self._stop_event.clear()
        self._logger.info(
            "Deepgram client configured (model=%s, language=%s, interim=%s, smart_format=%s, sample_rate=%s, endpointing_ms=%s).",
            self._model,
            self._language,
            self._interim_results,
            self._smart_format,
            self._sample_rate,
            self._endpointing_ms,
        )
        return super().connect()

    def close(self) -> None:
        self._stop_event.set()
        with self._connection_lock:
            has_connection = self._connection is not None
        self._logger.info("DEEPGRAM | event=close_requested | has_connection=%s", has_connection)
        super().close()

    def _build_ws_url(self) -> str:
        params = {
            "model": self._model,
            "language": self._language,
            "encoding": "linear16",
            "sample_rate": str(self._sample_rate),
            "channels": "1",
            "interim_results": "true" if self._interim_results else "false",
            "smart_format": "true" if self._smart_format else "false",
            "endpointing": str(max(10, self._endpointing_ms)),
        }
        return f"wss://api.deepgram.com/v1/listen?{urlencode(params)}"

    def _parse_transcript_events(self, message: str | bytes) -> Iterator[TranscriptEvent]:
        if not isinstance(message, str):
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self._logger.debug("Deepgram returned non-JSON message of length %s.", len(message))
            return

        if payload.get("type") != "Results":
            return

        channel = payload.get("channel") or {}
        alternatives = channel.get("alternatives") or []
        if not alternatives:
            return

        transcript = (alternatives[0].get("transcript") or "").strip()
        if not transcript:
            return

        is_final = bool(payload.get("is_final"))
        speech_final = bool(payload.get("speech_final"))

        if speech_final and not is_final:
            self._logger.debug(
                "DEEPGRAM | event=speech_final_only_skipped | text_len=%s | text=%r",
                len(transcript),
                transcript[:80],
            )
            return

        yield TranscriptEvent(text=transcript, is_final=is_final, source="deepgram")

    def stream_transcripts(self, audio_chunks: Iterable[bytes]) -> Iterator[TranscriptEvent]:
        if self._queued_events:
            yield from super().stream_transcripts(audio_chunks)
            return

        if ws_connect is None:
            self._logger.error(
                "websockets package is unavailable; using recovery fallback transcripts."
            )
            yield from super().stream_transcripts(audio_chunks)
            return

        if not self._connected:
            self.connect()

        self._stop_event.clear()
        stream_started = time.perf_counter()
        ws_url = self._build_ws_url()
        headers = {"Authorization": f"Token {self._api_key}"}
        sent_chunks = 0
        sender_errors: list[BaseException] = []
        first_response_latency_ms: float | None = None
        idle_after_sender = 0
        received_final = False
        finish_reason = "unknown"

        self._logger.info("DEEPGRAM | event=stream_connecting | url=%s", ws_url)
        try:
            with ws_connect(  # type: ignore[misc]
                ws_url,
                additional_headers=headers,
                open_timeout=10,
                close_timeout=1,
                max_size=2**20,
            ) as connection:
                with self._connection_lock:
                    self._connection = connection
                self._logger.info(
                    "DEEPGRAM | event=stream_connected | latency_ms=%.1f",
                    (time.perf_counter() - stream_started) * 1000,
                )

                def sender() -> None:
                    nonlocal sent_chunks
                    try:
                        for chunk in audio_chunks:
                            if self._stop_event.is_set():
                                break
                            if not chunk:
                                continue
                            connection.send(chunk)
                            sent_chunks += 1
                            if sent_chunks % 50 == 0:
                                self._logger.debug("DEEPGRAM | event=audio_sent | chunks=%s", sent_chunks)
                        with suppress(Exception):
                            connection.send(json.dumps({"type": "Finalize"}))
                    except BaseException as exc:  # pragma: no cover - network dependent
                        sender_errors.append(exc)
                    finally:
                        self._logger.info("DEEPGRAM | event=audio_sender_finished | chunks=%s", sent_chunks)

                sender_thread = threading.Thread(target=sender, daemon=True)
                sender_thread.start()

                while True:
                    try:
                        recv_timeout = 0.1 if self._stop_event.is_set() else 0.25
                        message = connection.recv(timeout=recv_timeout)
                        idle_after_sender = 0
                    except TimeoutError:
                        if sender_thread.is_alive():
                            continue
                        idle_after_sender += 1
                        if self._stop_event.is_set():
                            finish_reason = "stop_requested_idle"
                            break
                        if received_final and idle_after_sender >= 1:
                            finish_reason = "received_final_idle"
                            break
                        if idle_after_sender >= 4:
                            finish_reason = "idle_timeout"
                            break
                        continue
                    except ConnectionClosed as exc:
                        finish_reason = f"connection_closed:{type(exc).__name__}"
                        self._logger.info(
                            "DEEPGRAM | event=connection_closed | stop_requested=%s | error=%r",
                            self._stop_event.is_set(),
                            exc,
                        )
                        break

                    if message is None:
                        finish_reason = "message_none"
                        break

                    if first_response_latency_ms is None:
                        first_response_latency_ms = (time.perf_counter() - stream_started) * 1000
                        self._logger.info(
                            "DEEPGRAM | event=first_response | latency_ms=%.1f",
                            first_response_latency_ms,
                        )

                    for event in self._parse_transcript_events(message):
                        if event.is_final:
                            received_final = True
                        self._logger.debug(
                            "DEEPGRAM | event=transcript | final=%s | len=%s",
                            event.is_final,
                            len(event.text),
                        )
                        yield event

                sender_thread.join(timeout=3)
                if sender_errors:
                    sender_error = sender_errors[0]
                    if self._stop_event.is_set() and isinstance(sender_error, ConnectionClosed):
                        self._logger.info(
                            "DEEPGRAM | event=audio_sender_error_ignored | reason=%s | stop_requested=true",
                            type(sender_error).__name__,
                        )
                    else:
                        raise RuntimeError(f"Deepgram audio sender failed: {sender_error!r}")
        finally:
            with self._connection_lock:
                self._connection = None

        self._logger.info(
            "DEEPGRAM | event=stream_finished | sent_chunks=%s | first_response_ms=%s | received_final=%s | finish_reason=%s | total_latency_ms=%.1f",
            sent_chunks,
            "n/a" if first_response_latency_ms is None else f"{first_response_latency_ms:.1f}",
            received_final,
            finish_reason,
            (time.perf_counter() - stream_started) * 1000,
        )
