from config import AppConfig
from main import build_app
from stt_client import MockSTTClient
from text_inserter import TextInserter


def _make_capturing_inserter() -> tuple[TextInserter, list[str]]:
    """Create a TextInserter with a mock handler that captures inserted texts."""
    captured: list[str] = []

    def _capture(text: str) -> bool:
        captured.append(text)
        return True

    inserter = TextInserter(
        strategy_handlers={"type_direct": _capture, "ctrl_v": _capture},
        enable_system_insertion=False,
    )
    return inserter, captured


def test_app_flow_insert_final_fragment():
    cfg = AppConfig(stt_backend="mock", log_level="DEBUG")
    app = build_app(cfg)
    app.text_inserter, captured = _make_capturing_inserter()
    app.set_window_context("Recovered Terminal", "CASCADIA_HOSTING_WINDOW_CLASS")
    signal_counts = {"start": 0, "stop": 0}

    app.sound_notifier.notify_start = lambda: signal_counts.__setitem__(  # type: ignore[method-assign]
        "start", signal_counts["start"] + 1
    )
    app.sound_notifier.notify_stop = lambda: signal_counts.__setitem__(  # type: ignore[method-assign]
        "stop", signal_counts["stop"] + 1
    )

    assert app.start_recording() is True

    assert isinstance(app.stt_client, MockSTTClient)
    app.stt_client.queue_event("hello world", is_final=True)

    for _ in range(4):
        app.add_audio_chunk(b"\x00\x01" * 64, rms=800.0)

    stats = app.stop_recording()

    assert stats.status == "OK"
    assert stats.fragments_inserted == 1
    assert stats.chars_inserted == len("hello world")
    assert stats.window_hint == "terminal"
    assert signal_counts == {"start": 1, "stop": 1}


def test_app_flow_dedupes_repeated_final_transcript():
    cfg = AppConfig(stt_backend="mock", log_level="DEBUG", transcript_dedupe_window_ms=2000)
    app = build_app(cfg)
    app.text_inserter, captured = _make_capturing_inserter()
    app.set_window_context("Recovered Terminal", "CASCADIA_HOSTING_WINDOW_CLASS")
    app.sound_notifier.notify_start = lambda: None  # type: ignore[method-assign]
    app.sound_notifier.notify_stop = lambda: None  # type: ignore[method-assign]

    assert app.start_recording() is True
    assert isinstance(app.stt_client, MockSTTClient)
    app.stt_client.queue_event("same text", is_final=True)
    app.stt_client.queue_event("same text", is_final=True)

    app.add_audio_chunk(b"\x00\x01" * 64, rms=850.0)
    stats = app.stop_recording()

    assert stats.fragments_inserted == 1
    assert stats.chars_inserted == len("same text")
