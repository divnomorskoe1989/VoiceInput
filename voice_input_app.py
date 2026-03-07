from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import deque

from audio_recorder import AudioRecorder
from config import AppConfig, detect_window_hint
from contracts import SessionStats, TranscriptEvent
from sound_notifier import SoundNotifier
from stt_client import STTClient
from text_inserter import TextInserter
from text_normalizer import normalize_transcript_text
from tray_manager import TrayManager

_DEDUPE_STRIP_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize_for_dedupe(text: str) -> str:
    return " ".join(_DEDUPE_STRIP_RE.sub("", text).lower().split())


class VoiceInputApp:
    def __init__(
        self,
        config: AppConfig,
        recorder: AudioRecorder,
        stt_client: STTClient,
        text_inserter: TextInserter,
        tray_manager: TrayManager,
        sound_notifier: SoundNotifier,
    ) -> None:
        self.config = config
        self.recorder = recorder
        self.stt_client = stt_client
        self.text_inserter = text_inserter
        self.tray_manager = tray_manager
        self.sound_notifier = sound_notifier
        self._logger = logging.getLogger("VoiceInputApp")

        self._session_started_at = 0.0
        self._session_id = "idle"
        self._session_seq = 0
        self._state_lock = threading.RLock()
        self._inserted_fragments = 0
        self._inserted_chars = 0
        self._last_strategy = "none"
        self._window_title = ""
        self._window_class = ""
        self._interim = ""
        self._interim_inserted_text = ""
        self._last_final_hash = ""
        self._last_final_ts = 0.0
        self._recent_final_hashes: deque[str] = deque(maxlen=8)
        self._first_transcript_latency_ms: float | None = None
        self._first_insert_latency_ms: float | None = None
        self._interim_observed = False
        self._last_output_char = ""
        self._last_inserted_text = ""
        self._recent_inserted_normalized: deque[str] = deque(maxlen=8)
        self._collector_thread: threading.Thread | None = None
        self._collector_error: BaseException | None = None

        self.recorder.set_auto_stop_callback(self._on_auto_stop)

    def _step(self, event: str, level: str = "info", **fields: object) -> None:
        logger_method = getattr(self._logger, level.lower(), self._logger.info)
        payload = " | ".join(f"{key}={value}" for key, value in fields.items())
        if payload:
            logger_method("STEP | session=%s | event=%s | %s", self._session_id, event, payload)
            return
        logger_method("STEP | session=%s | event=%s", self._session_id, event)

    def set_window_context(self, title: str, class_name: str = "") -> None:
        self._window_title = title
        self._window_class = class_name
        self._step("window_context_set", title=repr(title), class_name=repr(class_name))

    def start_recording(self) -> bool:
        with self._state_lock:
            if self.recorder.is_running:
                self._step("start_ignored_already_running")
                return False

            self._session_seq += 1
            self._session_id = f"s{self._session_seq:05d}"
            self._step("start_requested", mode=self.config.session_mode, hotkey=self.config.hotkey)

            # Run STT connect and recorder start in parallel
            parallel_started = time.perf_counter()
            connect_error: list[BaseException] = []

            def _connect_stt() -> None:
                try:
                    self.stt_client.connect()
                except BaseException as exc:
                    connect_error.append(exc)

            connect_thread = threading.Thread(target=_connect_stt, daemon=True)
            connect_thread.start()
            self.recorder.start()
            connect_thread.join(timeout=10)
            if connect_error:
                self.recorder.stop()
                raise connect_error[0]
            self._step(
                "parallel_start_completed",
                latency_ms=f"{(time.perf_counter() - parallel_started) * 1000:.1f}",
            )

            self._session_started_at = time.monotonic()
            self._inserted_fragments = 0
            self._inserted_chars = 0
            self._last_strategy = "none"
            self._interim = ""
            self._interim_inserted_text = ""
            self._last_final_hash = ""
            self._last_final_ts = 0.0
            self._recent_final_hashes.clear()
            self._first_transcript_latency_ms = None
            self._first_insert_latency_ms = None
            self._interim_observed = False
            self._last_output_char = ""
            self._last_inserted_text = ""
            self._recent_inserted_normalized.clear()
            self._collector_error = None
            self._collector_thread = threading.Thread(target=self._collect_transcripts_worker, daemon=True)
            self._collector_thread.start()
            self._step("transcript_worker_started")

            # Sound and tray update are non-blocking (sound is queued to worker thread)
            self.sound_notifier.notify_start()
            self.tray_manager.set_recording(True)

            self._logger.info("Recording session started (mode=%s).", self.config.session_mode)
            self._step("session_started")
            return True

    def add_audio_chunk(self, chunk: bytes, rms: float | None = None) -> None:
        self._step(
            "audio_chunk_received",
            level="debug",
            size=len(chunk),
            rms="none" if rms is None else f"{rms:.1f}",
        )
        self.recorder.push_chunk(chunk, rms=rms)

    def _insert_text_fragment(self, text: str, transcript_kind: str) -> None:
        if not text:
            return
        normalized_text = normalize_transcript_text(text)
        if self._last_output_char:
            if self._last_output_char.isspace():
                normalized_text = normalized_text.lstrip()
            elif normalized_text and not normalized_text[0].isspace():
                if (
                    self._last_output_char.isalnum()
                    and normalized_text[0].isalnum()
                ) or (
                    self._last_output_char in ".,!?;:"
                    and normalized_text[0].isalnum()
                ):
                    normalized_text = " " + normalized_text
        if not normalized_text:
            return

        # Fuzzy dedup: check against ring buffer of recent inserts (normalized)
        norm_for_dedup = _normalize_for_dedupe(normalized_text)
        if norm_for_dedup and norm_for_dedup in self._recent_inserted_normalized:
            self._step(
                "insert_skipped_duplicate",
                level="warning",
                mechanism="fuzzy_ring_buffer",
                text_len=len(normalized_text),
                normalized=repr(norm_for_dedup[:60]),
            )
            return

        result = self.text_inserter.insert_text(
            normalized_text,
            window_title=self._window_title,
            window_class=self._window_class,
        )
        self._step(
            "insert_attempt",
            transcript_kind=transcript_kind,
            strategy=result.strategy,
            success=result.success,
            executed=result.executed,
            latency_ms=f"{result.latency_ms:.1f}",
            text_len=len(normalized_text),
        )
        if result.success:
            self._inserted_fragments += 1
            self._inserted_chars += len(normalized_text)
            self._last_strategy = result.strategy
            self._last_output_char = normalized_text[-1]
            self._last_inserted_text = normalized_text
            if norm_for_dedup:
                self._recent_inserted_normalized.append(norm_for_dedup)
            self._logger.debug("INSERTED_TEXT | kind=%s | text=%r", transcript_kind, normalized_text)
            if self._first_insert_latency_ms is None:
                self._first_insert_latency_ms = max(0.0, (time.monotonic() - self._session_started_at) * 1000)
                self._step("first_insert_completed", latency_ms=f"{self._first_insert_latency_ms:.1f}")

    def _extract_stable_interim_delta(self, interim_text: str) -> str:
        committed = self._interim_inserted_text
        if not interim_text:
            return ""

        # Exact prefix check (fast path)
        if committed and interim_text.startswith(committed):
            delta = interim_text[len(committed):]
            if not delta:
                return ""
            words = delta.split()
            if len(words) < 5:
                return ""
            stable = " ".join(words[:-4]) + " "
            return stable

        # Fuzzy prefix check: use normalized words when Deepgram adds punctuation
        if committed:
            norm_committed = _normalize_for_dedupe(committed)
            norm_interim = _normalize_for_dedupe(interim_text)
            if not norm_interim.startswith(norm_committed):
                return ""
            # Committed words match; extract NEW words from interim
            committed_word_count = len(norm_committed.split()) if norm_committed else 0
            interim_words = norm_interim.split()
            new_words = interim_words[committed_word_count:]
            if len(new_words) < 5:
                return ""
            # Use original interim text to get properly formatted words
            # Skip committed_word_count words in original interim_text
            fi = 0
            words_skipped = 0
            in_word = False
            while fi < len(interim_text) and words_skipped < committed_word_count:
                is_wc = interim_text[fi].isalnum() or interim_text[fi] == '_'
                if is_wc and not in_word:
                    in_word = True
                elif not is_wc and in_word:
                    words_skipped += 1
                    in_word = False
                fi += 1
            if in_word:
                words_skipped += 1
            # Skip trailing non-word chars
            while fi < len(interim_text) and not (interim_text[fi].isalnum() or interim_text[fi] == '_'):
                fi += 1
            remaining = interim_text[fi:]
            words = remaining.split()
            if len(words) < 5:
                return ""
            stable = " ".join(words[:-4]) + " "
            return stable

        # No committed text yet — extract from full interim
        words = interim_text.split()
        if len(words) < 5:
            return ""
        stable = " ".join(words[:-4]) + " "
        return stable

    def _trim_final_with_interim(self, final_text: str) -> tuple[str, int]:
        committed = self._interim_inserted_text
        if not committed:
            return final_text, 0

        # Exact prefix match (fast path)
        if final_text.startswith(committed):
            return final_text[len(committed):], len(committed)

        norm_committed = _normalize_for_dedupe(committed)
        norm_final = _normalize_for_dedupe(final_text)

        if not norm_committed:
            return final_text, 0

        # Full overlap: committed covers all (or more than) final content
        if norm_final == norm_committed or norm_committed.startswith(norm_final):
            self._step(
                "trim_final_fully_covered",
                committed_len=len(committed),
                final_len=len(final_text),
            )
            return "", len(final_text)

        # Partial overlap: final starts with committed (word-based alignment)
        if norm_final.startswith(norm_committed):
            committed_word_count = len(norm_committed.split())
            return self._skip_n_words_in_original(final_text, committed_word_count)

        # Suffix-prefix overlap: committed tail matches final head (word-based)
        committed_words = norm_committed.split()
        final_words = norm_final.split()
        best_word_overlap = 0
        max_check = min(len(committed_words), len(final_words))
        for n in range(max_check, 0, -1):
            if committed_words[-n:] == final_words[:n]:
                best_word_overlap = n
                break
        if best_word_overlap >= 1:
            return self._skip_n_words_in_original(final_text, best_word_overlap)

        self._step(
            "trim_final_no_overlap",
            level="warning",
            committed=repr(committed[:60]),
            final=repr(final_text[:60]),
            norm_committed=repr(norm_committed[:60]),
            norm_final=repr(norm_final[:60]),
        )
        return final_text, 0

    @staticmethod
    def _skip_n_words_in_original(text: str, word_count: int) -> tuple[str, int]:
        """Skip first N words in text (by word boundaries), return remainder and offset."""
        fi = 0
        words_skipped = 0
        in_word = False
        while fi < len(text) and words_skipped < word_count:
            is_wc = text[fi].isalnum() or text[fi] == '_'
            if is_wc and not in_word:
                in_word = True
            elif not is_wc and in_word:
                words_skipped += 1
                in_word = False
            fi += 1
        if in_word:
            words_skipped += 1
        while fi < len(text) and not (text[fi].isalnum() or text[fi] == '_'):
            fi += 1
        if words_skipped >= word_count:
            return text[fi:], fi
        return text, 0

    def _handle_transcript(self, event: TranscriptEvent) -> None:
        if not event.text:
            self._step("transcript_ignored_empty", level="debug", is_final=event.is_final)
            return

        if self._first_transcript_latency_ms is None:
            self._first_transcript_latency_ms = max(0.0, (time.monotonic() - self._session_started_at) * 1000)
            self._step("first_transcript_received", latency_ms=f"{self._first_transcript_latency_ms:.1f}")

        if not event.is_final:
            previous_interim = self._interim
            self._interim = event.text
            self._logger.debug("Transcript received: final=%s len=%s", event.is_final, len(event.text))
            self._step("transcript_interim", level="debug", length=len(event.text))
            self._interim_observed = True
            if not self.config.interim_insert_enabled:
                return
            if previous_interim and not event.text.startswith(previous_interim):
                self._step(
                    "transcript_interim_revision",
                    level="debug",
                    previous_len=len(previous_interim),
                    current_len=len(event.text),
                )
                return
            stable_delta = self._extract_stable_interim_delta(event.text)
            if not stable_delta:
                return
            self._insert_text_fragment(stable_delta, transcript_kind="interim")
            self._interim_inserted_text += stable_delta
            self._step(
                "transcript_interim_committed",
                level="debug",
                committed_len=len(self._interim_inserted_text),
            )
            return

        # --- Final transcript dedup (normalized hash + ring buffer) ---
        norm_text = _normalize_for_dedupe(event.text)
        final_hash = hashlib.sha1(norm_text.encode("utf-8", errors="ignore")).hexdigest()
        now = time.monotonic()
        dedupe_window_sec = max(0, self.config.transcript_dedupe_window_ms) / 1000

        # Check against last final (time-windowed)
        if (
            self._last_final_hash == final_hash
            and self._last_final_ts > 0.0
            and (now - self._last_final_ts) <= dedupe_window_sec
        ):
            self._step(
                "transcript_final_deduped",
                mechanism="exact_hash_window",
                length=len(event.text),
                normalized=repr(norm_text[:60]),
                dedupe_window_ms=self.config.transcript_dedupe_window_ms,
            )
            return

        # Check against ring buffer of recent finals
        if final_hash in self._recent_final_hashes:
            self._step(
                "transcript_final_deduped",
                mechanism="ring_buffer",
                length=len(event.text),
                normalized=repr(norm_text[:60]),
            )
            return

        self._last_final_hash = final_hash
        self._last_final_ts = now
        self._recent_final_hashes.append(final_hash)
        self._step("transcript_final", length=len(event.text), normalized_hash=final_hash[:12])
        final_text = event.text
        if self.config.interim_insert_enabled and self._interim_inserted_text:
            final_text, overlap = self._trim_final_with_interim(final_text)
            if overlap > 0:
                self._step(
                    "transcript_final_trimmed_by_interim",
                    trimmed_len=overlap,
                    remaining_len=len(final_text),
                    remaining=repr(final_text[:50]),
                )
            else:
                self._step(
                    "transcript_final_not_aligned_with_interim",
                    level="warning",
                    committed_len=len(self._interim_inserted_text),
                    committed=repr(self._interim_inserted_text[:50]),
                    final_len=len(event.text),
                    final=repr(event.text[:50]),
                )
        if final_text:
            self._insert_text_fragment(final_text, transcript_kind="final")
        else:
            self._step("transcript_final_fully_covered_by_interim", level="debug")
        self._interim = ""
        self._interim_inserted_text = ""

    def _collect_transcripts(self) -> None:
        self._step("transcript_collection_started")
        for event in self.stt_client.stream_transcripts(self.recorder.iter_chunks()):
            self._handle_transcript(event)
        self._step("transcript_collection_finished")

    def _collect_transcripts_worker(self) -> None:
        try:
            self._collect_transcripts()
        except BaseException as exc:
            self._collector_error = exc
            self._step("transcript_collection_error", level="error", error=repr(exc))
            self._logger.exception("Transcript collection worker crashed.")

    def _wait_transcript_worker(self, timeout_sec: float) -> bool:
        if self._collector_thread is None:
            return True
        join_started = time.perf_counter()
        self._collector_thread.join(timeout=timeout_sec)
        finished = not self._collector_thread.is_alive()
        self._step(
            "transcript_worker_join",
            timeout_sec=f"{timeout_sec:.1f}",
            finished=finished,
            latency_ms=f"{(time.perf_counter() - join_started) * 1000:.1f}",
        )
        if finished:
            self._collector_thread = None
        return finished

    def stop_recording(self) -> SessionStats:
        with self._state_lock:
            if not self.recorder.is_running:
                self._step("stop_ignored_not_running")
                return SessionStats(status="IDLE", mode=self.config.session_mode)

            self._step("stop_requested")

            # Play stop sound IMMEDIATELY for instant feedback
            self.sound_notifier.notify_stop()
            self.tray_manager.set_recording(False)

            recorder_stop_started = time.perf_counter()
            self.recorder.stop()
            self._step("recorder_stopped", latency_ms=f"{(time.perf_counter() - recorder_stop_started) * 1000:.1f}")

            # Close STT in background while waiting for transcript worker to drain
            collect_started = time.perf_counter()

            def _close_stt() -> None:
                self.stt_client.close()

            close_thread = threading.Thread(target=_close_stt, daemon=True)
            close_thread.start()

            worker_finished = self._wait_transcript_worker(timeout_sec=0.4)
            close_thread.join(timeout=1.0)

            if not worker_finished:
                self._step("transcript_worker_timeout", level="warning", timeout_sec=0.4)
                self._wait_transcript_worker(timeout_sec=0.8)
            if self._collector_thread is not None and self._collector_thread.is_alive():
                self._step("transcript_worker_wait_extended", level="warning")
                self._wait_transcript_worker(timeout_sec=1.5)
            self._step("transcripts_collected", latency_ms=f"{(time.perf_counter() - collect_started) * 1000:.1f}")

            elapsed = max(0.0, time.monotonic() - self._session_started_at)
            window_hint = detect_window_hint(self._window_title)
            collector_alive = self._collector_thread is not None and self._collector_thread.is_alive()
            status = "OK" if self._collector_error is None and not collector_alive else "ERROR"
            metadata = {"strategy": self._last_strategy}
            if self._collector_error is not None:
                metadata["collector_error"] = repr(self._collector_error)
            if collector_alive:
                metadata["collector_alive"] = "true"

            stats = SessionStats(
                duration_sec=elapsed,
                fragments_inserted=self._inserted_fragments,
                chars_inserted=self._inserted_chars,
                window_hint=window_hint,
                mode=self.config.session_mode,
                status=status,
                metadata=metadata,
            )
            self._step(
                "session_finished",
                duration_sec=f"{stats.duration_sec:.3f}",
                fragments=stats.fragments_inserted,
                chars=stats.chars_inserted,
                first_transcript_latency_ms="n/a"
                if self._first_transcript_latency_ms is None
                else f"{self._first_transcript_latency_ms:.1f}",
                first_insert_latency_ms="n/a"
                if self._first_insert_latency_ms is None
                else f"{self._first_insert_latency_ms:.1f}",
                strategy=self._last_strategy,
                status=stats.status,
            )
            self._logger.info(
                "SESSION_DIAG | duration=%.1fs | fragments=%s | chars=%s | interim_used=%s | mode=%s | window=%s | strategy=%s | status=%s",
                stats.duration_sec,
                stats.fragments_inserted,
                stats.chars_inserted,
                "yes" if self._interim_observed else "no",
                stats.mode,
                stats.window_hint,
                self._last_strategy,
                stats.status,
            )
            return stats

    def toggle_recording(self) -> SessionStats | None:
        self._step("toggle_requested", currently_running=self.recorder.is_running)
        if self.recorder.is_running:
            result = self.stop_recording()
            self._step("toggle_completed", action="stop", status=result.status)
            return result

        started = self.start_recording()
        self._step("toggle_completed", action="start", started=started)
        return None

    def _on_auto_stop(self) -> None:
        self._logger.info("Auto-stop triggered by silence timeout.")
        self._step("auto_stop_triggered")
        if self.recorder.is_running:
            self.stop_recording()
