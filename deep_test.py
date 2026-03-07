from __future__ import annotations

from config import AppConfig
from main import build_app
from stt_client import MockSTTClient


def run() -> None:
    config = AppConfig.from_env()
    config.stt_backend = "mock"
    app = build_app(config)
    app.set_window_context("Recovered Terminal", "CASCADIA_HOSTING_WINDOW_CLASS")
    app.start_recording()

    if isinstance(app.stt_client, MockSTTClient):
        app.stt_client.queue_event("deep test transcript", is_final=True)

    for _ in range(10):
        app.add_audio_chunk(b"\x00\x01" * 128, rms=850.0)

    stats = app.stop_recording()
    print(f"ok: fragments={stats.fragments_inserted} chars={stats.chars_inserted}")


if __name__ == "__main__":
    run()
