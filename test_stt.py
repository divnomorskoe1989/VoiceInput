from stt_client import MockSTTClient


def test_mock_stt_queued_events_take_priority():
    client = MockSTTClient()
    client.connect()
    client.queue_event("part", is_final=False)
    client.queue_event("final", is_final=True)

    events = list(client.stream_transcripts([b"x", b"y"]))

    assert [e.text for e in events] == ["part", "final"]
    assert [e.is_final for e in events] == [False, True]


def test_mock_stt_generates_default_final_when_audio_exists():
    client = MockSTTClient()
    client.connect()
    client.set_default_final_text("ok")

    events = list(client.stream_transcripts([b"x"]))

    assert len(events) == 1
    assert events[0].is_final is True
    assert events[0].text == "ok"


def test_deepgram_sender_connection_closed_ignored_after_stop(monkeypatch):
    from stt_client import DeepgramSTTClient

    class FakeClosed(Exception):
        pass

    class FakeConnection:
        def __init__(self, client):
            self._client = client
            self._recv_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send(self, _payload):
            raise FakeClosed("closed while sending")

        def recv(self, timeout=0.25):
            self._recv_calls += 1
            self._client._stop_event.set()  # noqa: SLF001 - test controlled state
            raise TimeoutError()

    monkeypatch.setattr("stt_client.ConnectionClosed", FakeClosed)
    monkeypatch.setattr("stt_client.ws_connect", lambda *args, **kwargs: FakeConnection(client))

    client = DeepgramSTTClient(api_key="test-key")
    client.connect()

    events = list(client.stream_transcripts([b"\x00\x01"]))

    assert events == []


def test_deepgram_sender_connection_closed_is_error_without_stop(monkeypatch):
    import pytest
    from stt_client import DeepgramSTTClient

    class FakeClosed(Exception):
        pass

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def send(self, _payload):
            raise FakeClosed("closed while sending")

        def recv(self, timeout=0.25):
            raise TimeoutError()

    monkeypatch.setattr("stt_client.ConnectionClosed", FakeClosed)
    monkeypatch.setattr("stt_client.ws_connect", lambda *args, **kwargs: FakeConnection())

    client = DeepgramSTTClient(api_key="test-key")
    client.connect()

    with pytest.raises(RuntimeError, match="Deepgram audio sender failed"):
        list(client.stream_transcripts([b"\x00\x01"]))
