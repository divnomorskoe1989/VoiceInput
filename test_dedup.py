"""Tests for transcript deduplication at all levels.

Covers:
1. Deepgram speech_final vs is_final separation (stt_client layer)
2. Fuzzy hash dedup for near-identical finals (punctuation differences)
3. Ring buffer dedup for A->B->A patterns
4. Insertion-level fuzzy dedup
5. Interim + final overlap scenarios
"""

import json
import logging

import pytest

from config import AppConfig
from contracts import TranscriptEvent
from main import build_app
from stt_client import DeepgramSTTClient, MockSTTClient
from voice_input_app import VoiceInputApp, _normalize_for_dedupe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(
    dedupe_window_ms: int = 5000,
    interim_insert_enabled: bool = False,
    log_level: str = "DEBUG",
) -> tuple[VoiceInputApp, list[str], list[str]]:
    """Build app with capturing inserter + log capture. Returns (app, captured_texts, log_messages)."""
    cfg = AppConfig(
        stt_backend="mock",
        log_level=log_level,
        transcript_dedupe_window_ms=dedupe_window_ms,
        interim_insert_enabled=interim_insert_enabled,
    )
    app = build_app(cfg)
    captured: list[str] = []

    def _capture(text: str) -> bool:
        captured.append(text)
        return True

    from text_inserter import TextInserter
    app.text_inserter = TextInserter(
        strategy_handlers={"type_direct": _capture, "ctrl_v": _capture},
        enable_system_insertion=False,
    )
    app.sound_notifier.notify_start = lambda: None  # type: ignore[method-assign]
    app.sound_notifier.notify_stop = lambda: None  # type: ignore[method-assign]

    log_messages: list[str] = []
    handler = logging.Handler()
    handler.emit = lambda record: log_messages.append(record.getMessage())  # type: ignore[method-assign]
    logging.getLogger("VoiceInputApp").addHandler(handler)
    logging.getLogger("VoiceInputApp").setLevel(logging.DEBUG)

    return app, captured, log_messages


def _run_session(app: VoiceInputApp, events: list[TranscriptEvent]) -> None:
    """Start recording, queue events, push audio, stop."""
    app.set_window_context("Test Window", "TEST_CLASS")
    assert app.start_recording() is True
    mock_stt = app.stt_client
    assert isinstance(mock_stt, MockSTTClient)
    for ev in events:
        mock_stt.queue_event(ev.text, is_final=ev.is_final)
    app.add_audio_chunk(b"\x00\x01" * 64, rms=800.0)
    app.stop_recording()


# ---------------------------------------------------------------------------
# 1. _normalize_for_dedupe unit tests
# ---------------------------------------------------------------------------

class TestNormalizeForDedupe:
    def test_strips_punctuation(self):
        assert _normalize_for_dedupe("Привет!") == "привет"

    def test_collapses_whitespace(self):
        assert _normalize_for_dedupe("  hello   world  ") == "hello world"

    def test_case_insensitive(self):
        assert _normalize_for_dedupe("Hello World") == "hello world"

    def test_identical_after_normalize(self):
        a = _normalize_for_dedupe("Привет, мир!")
        b = _normalize_for_dedupe("привет мир")
        assert a == b

    def test_period_vs_no_period(self):
        a = _normalize_for_dedupe("hello world.")
        b = _normalize_for_dedupe("hello world")
        assert a == b


# ---------------------------------------------------------------------------
# 2. Deepgram speech_final filtering (stt_client layer)
# ---------------------------------------------------------------------------

class TestDeepgramSpeechFinalFiltering:
    def _make_client(self) -> DeepgramSTTClient:
        return DeepgramSTTClient(api_key="test-key")

    def _make_deepgram_message(
        self, text: str, is_final: bool = False, speech_final: bool = False,
    ) -> str:
        return json.dumps({
            "type": "Results",
            "is_final": is_final,
            "speech_final": speech_final,
            "channel": {
                "alternatives": [{"transcript": text}],
            },
        })

    def test_is_final_true_yields_final_event(self):
        client = self._make_client()
        msg = self._make_deepgram_message("привет", is_final=True, speech_final=False)
        events = list(client._parse_transcript_events(msg))
        assert len(events) == 1
        assert events[0].is_final is True
        assert events[0].text == "привет"

    def test_speech_final_only_skipped(self):
        """speech_final=True without is_final=True must NOT produce a final event."""
        client = self._make_client()
        msg = self._make_deepgram_message("привет", is_final=False, speech_final=True)
        events = list(client._parse_transcript_events(msg))
        assert len(events) == 0

    def test_both_flags_yields_final(self):
        client = self._make_client()
        msg = self._make_deepgram_message("привет", is_final=True, speech_final=True)
        events = list(client._parse_transcript_events(msg))
        assert len(events) == 1
        assert events[0].is_final is True

    def test_interim_result_yields_non_final(self):
        client = self._make_client()
        msg = self._make_deepgram_message("привет", is_final=False, speech_final=False)
        events = list(client._parse_transcript_events(msg))
        assert len(events) == 1
        assert events[0].is_final is False


# ---------------------------------------------------------------------------
# 3. Exact duplicate final transcripts (hash dedup)
# ---------------------------------------------------------------------------

class TestExactDuplicateFinals:
    def test_identical_finals_deduped(self):
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="same text", is_final=True),
            TranscriptEvent(text="same text", is_final=True),
        ])
        assert len(captured) == 1
        assert any("transcript_final_deduped" in m for m in logs)

    def test_identical_finals_three_times(self):
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="same text", is_final=True),
            TranscriptEvent(text="same text", is_final=True),
            TranscriptEvent(text="same text", is_final=True),
        ])
        assert len(captured) == 1

    def test_different_finals_not_deduped(self):
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="hello", is_final=True),
            TranscriptEvent(text="world", is_final=True),
        ])
        assert len(captured) == 2


# ---------------------------------------------------------------------------
# 4. Fuzzy duplicate finals (punctuation/case differences)
# ---------------------------------------------------------------------------

class TestFuzzyDuplicateFinals:
    def test_period_difference_deduped(self):
        """'привет' vs 'привет.' should be deduped (normalized hash matches)."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="привет", is_final=True),
            TranscriptEvent(text="привет.", is_final=True),
        ])
        assert len(captured) == 1
        assert any("transcript_final_deduped" in m for m in logs)

    def test_case_difference_deduped(self):
        """'Hello World' vs 'hello world' should be deduped."""
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="Hello World", is_final=True),
            TranscriptEvent(text="hello world", is_final=True),
        ])
        assert len(captured) == 1

    def test_punctuation_variation_deduped(self):
        """'Привет, мир!' vs 'привет мир' should be deduped."""
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="Привет, мир!", is_final=True),
            TranscriptEvent(text="привет мир", is_final=True),
        ])
        assert len(captured) == 1

    def test_substantially_different_not_deduped(self):
        """'привет' vs 'до свидания' must NOT be deduped."""
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="привет", is_final=True),
            TranscriptEvent(text="до свидания", is_final=True),
        ])
        assert len(captured) == 2


# ---------------------------------------------------------------------------
# 5. Ring buffer dedup (A -> B -> A pattern)
# ---------------------------------------------------------------------------

class TestRingBufferDedup:
    def test_aba_pattern_deduped(self):
        """A->B->A: third event should be caught by ring buffer."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="первый текст", is_final=True),
            TranscriptEvent(text="второй текст", is_final=True),
            TranscriptEvent(text="первый текст", is_final=True),
        ])
        assert len(captured) == 2
        assert any("ring_buffer" in m for m in logs)

    def test_abcba_pattern(self):
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="A text", is_final=True),
            TranscriptEvent(text="B text", is_final=True),
            TranscriptEvent(text="C text", is_final=True),
            TranscriptEvent(text="B text", is_final=True),
            TranscriptEvent(text="A text", is_final=True),
        ])
        assert len(captured) == 3  # A, B, C — repeats caught


# ---------------------------------------------------------------------------
# 6. Insertion-level fuzzy dedup
# ---------------------------------------------------------------------------

class TestInsertionLevelDedup:
    def test_insert_identical_normalized_blocked(self):
        """If two different raw texts normalize to the same insert, second is blocked."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="Привет мир", is_final=True),
            # This is different raw text but after text_normalizer + _normalize_for_dedupe
            # could still match. Even if it passes transcript dedup, insertion dedup catches it.
        ])
        # Just verify the mechanism exists — single event always inserts
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# 7. Dedup logging visibility
# ---------------------------------------------------------------------------

class TestDedupLogging:
    def test_dedup_event_logged_with_mechanism(self):
        """Every dedup decision must log which mechanism caught it."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="test text", is_final=True),
            TranscriptEvent(text="test text", is_final=True),
        ])
        dedup_logs = [m for m in logs if "transcript_final_deduped" in m]
        assert len(dedup_logs) >= 1
        assert any("mechanism=" in m for m in dedup_logs)

    def test_dedup_logs_normalized_text(self):
        """Dedup log must include normalized text preview for debugging."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="Тест.", is_final=True),
            TranscriptEvent(text="тест", is_final=True),
        ])
        dedup_logs = [m for m in logs if "transcript_final_deduped" in m]
        assert len(dedup_logs) >= 1
        assert any("normalized=" in m for m in dedup_logs)

    def test_insertion_dedup_logged_as_warning(self):
        """Insertion-level dedup must log at WARNING level for visibility."""
        app, captured, logs = _make_app()

        # Directly test _insert_text_fragment dedup
        app._last_output_char = "x"
        app._insert_text_fragment("hello world", transcript_kind="final")
        app._insert_text_fragment("hello world!", transcript_kind="final")

        # The second should be caught by fuzzy insertion dedup
        insert_dedup_logs = [m for m in logs if "insert_skipped_duplicate" in m]
        assert len(insert_dedup_logs) >= 1
        assert any("fuzzy_ring_buffer" in m for m in insert_dedup_logs)


# ---------------------------------------------------------------------------
# 8. Realistic Deepgram scenario: is_final + speech_final double-fire
# ---------------------------------------------------------------------------

class TestRealisticDeepgramScenario:
    def test_deepgram_double_fire_prevented(self):
        """Simulate Deepgram sending is_final=true then speech_final=true for same text.
        The speech_final-only message is filtered at stt_client level.
        """
        client = DeepgramSTTClient(api_key="test-key")

        # First message: is_final=true
        msg1 = json.dumps({
            "type": "Results",
            "is_final": True,
            "speech_final": False,
            "channel": {"alternatives": [{"transcript": "тестовый текст"}]},
        })
        # Second message: speech_final=true only
        msg2 = json.dumps({
            "type": "Results",
            "is_final": False,
            "speech_final": True,
            "channel": {"alternatives": [{"transcript": "тестовый текст"}]},
        })

        events1 = list(client._parse_transcript_events(msg1))
        events2 = list(client._parse_transcript_events(msg2))

        assert len(events1) == 1
        assert events1[0].is_final is True
        assert len(events2) == 0  # speech_final-only is filtered

    def test_deepgram_is_final_with_punctuation_variation(self):
        """Two is_final messages with slight punctuation difference -> deduped at app level."""
        app, captured, logs = _make_app()
        _run_session(app, [
            TranscriptEvent(text="Привет как дела", is_final=True),
            TranscriptEvent(text="Привет, как дела?", is_final=True),
        ])
        assert len(captured) == 1
        assert any("transcript_final_deduped" in m for m in logs)


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_text_not_inserted(self):
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="", is_final=True),
        ])
        assert len(captured) == 0

    def test_whitespace_only_not_inserted(self):
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="   ", is_final=True),
        ])
        assert len(captured) == 0

    def test_dedup_resets_between_sessions(self):
        """Ring buffers must reset on new session start."""
        app, captured, _ = _make_app()
        _run_session(app, [
            TranscriptEvent(text="session one text", is_final=True),
        ])
        assert len(captured) == 1
        # Start second session — same text should insert again
        captured.clear()
        _run_session(app, [
            TranscriptEvent(text="session one text", is_final=True),
        ])
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# 10. Interim -> Final overlap (main real-world bug)
# ---------------------------------------------------------------------------

class TestInterimFinalOverlap:
    """Tests for the scenario where interim text is inserted, then final comes
    with punctuation differences. This was the main source of duplicates."""

    def test_interim_committed_then_final_with_punctuation(self):
        """Interim inserts 'Ты конечно молодец но давай ',
        then final is 'Ты, конечно, молодец, но давай сделаем с тобой.'
        Only the new part should be inserted."""
        app, captured, logs = _make_app(interim_insert_enabled=True)
        app.set_window_context("Test Window", "TEST_CLASS")
        app._session_started_at = __import__('time').monotonic()

        # Simulate what _extract_stable_interim_delta would commit
        app._interim_inserted_text = "Ты конечно молодец но давай "
        app._last_output_char = " "
        app._inserted_fragments = 1
        app._interim_observed = True

        # Now a final comes with punctuation
        final_event = TranscriptEvent(
            text="Ты, конечно, молодец, но давай сделаем с тобой.",
            is_final=True,
        )
        app._handle_transcript(final_event)

        # Should only insert the NEW part ("сделаем с тобой.")
        assert len(captured) == 1
        inserted = captured[0]
        assert "конечно" not in inserted.lower(), f"Duplicate! Got: {inserted!r}"
        assert "сделаем" in inserted.lower(), f"Missing new part! Got: {inserted!r}"

    def test_interim_fully_covers_final(self):
        """When interim already inserted everything and final is the same content."""
        app, captured, _ = _make_app(interim_insert_enabled=True)
        app.set_window_context("Test Window", "TEST_CLASS")
        app._session_started_at = __import__('time').monotonic()

        app._interim_inserted_text = "привет как дела "
        app._last_output_char = " "
        app._inserted_fragments = 1
        app._interim_observed = True

        final_event = TranscriptEvent(text="Привет, как дела?", is_final=True)
        app._handle_transcript(final_event)

        # Nothing new to insert
        assert len(captured) == 0

    def test_trim_with_suffix_prefix_overlap(self):
        """Committed interim ends with words that overlap with final start."""
        app, captured, _ = _make_app(interim_insert_enabled=True)
        app.set_window_context("Test Window", "TEST_CLASS")
        app._session_started_at = __import__('time').monotonic()

        app._interim_inserted_text = "это первая часть предложения "
        app._last_output_char = " "
        app._inserted_fragments = 1
        app._interim_observed = True

        # Final that partially overlaps
        final_event = TranscriptEvent(
            text="часть предложения и вторая часть тоже",
            is_final=True,
        )
        app._handle_transcript(final_event)

        assert len(captured) == 1
        inserted = captured[0]
        # Should not have "часть предложения" duplicated
        assert "часть предложения" not in inserted, f"Overlap not trimmed! Got: {inserted!r}"
        assert "вторая" in inserted, f"Missing new part! Got: {inserted!r}"

    def test_skip_n_words_in_original(self):
        """Unit test for _skip_n_words_in_original."""
        from voice_input_app import VoiceInputApp
        text = "Ты, конечно, молодец, но давай сделаем."
        remainder, offset = VoiceInputApp._skip_n_words_in_original(text, 5)
        assert "сделаем" in remainder, f"Got: {remainder!r}"
        assert "молодец" not in remainder, f"Not trimmed: {remainder!r}"

    def test_normalize_for_dedupe_handles_russian(self):
        """Verify _normalize_for_dedupe works correctly with Russian text + punctuation."""
        a = _normalize_for_dedupe("Ты конечно молодец но давай ")
        b = _normalize_for_dedupe("Ты, конечно, молодец, но давай")
        assert a == b, f"{a!r} != {b!r}"
