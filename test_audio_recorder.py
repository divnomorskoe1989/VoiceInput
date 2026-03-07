from audio_recorder import AudioRecorder


def test_audio_recorder_auto_stop_on_silence():
    now = [0.0]
    fired = {"value": False}

    def time_fn():
        return now[0]

    recorder = AudioRecorder(
        silence_timeout_sec=1.0,
        silence_rms_threshold=10.0,
        time_fn=time_fn,
    )
    recorder.set_auto_stop_callback(lambda: fired.__setitem__("value", True))

    recorder.start()
    recorder.push_chunk(b"a", rms=20.0)
    now[0] = 0.5
    recorder.push_chunk(b"b", rms=1.0)
    assert fired["value"] is False

    now[0] = 1.2
    recorder.push_chunk(b"c", rms=1.0)
    assert fired["value"] is True


def test_audio_recorder_collects_session_rms_metrics():
    now = [0.0]

    def time_fn():
        return now[0]

    recorder = AudioRecorder(
        silence_timeout_sec=5.0,
        silence_rms_threshold=10.0,
        time_fn=time_fn,
    )

    recorder.start()
    recorder.push_chunk(b"a", rms=20.0)
    now[0] = 0.1
    recorder.push_chunk(b"b", rms=5.0)
    now[0] = 0.2
    recorder.push_chunk(b"c", rms=15.0)
    now[0] = 0.3
    recorder.stop()

    assert recorder._session_chunks_total == 3
    assert recorder._session_voice_chunks == 2
    assert recorder._session_silence_chunks == 1
    assert recorder._session_rms_count == 3
    assert recorder._session_rms_max == 20.0
