from config import AppConfig


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("VOICEINPUT_SAMPLE_RATE", "22050")
    monkeypatch.setenv("VOICEINPUT_SILENCE_TIMEOUT_SEC", "2.5")
    monkeypatch.setenv("VOICEINPUT_STT_BACKEND", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "abc")
    monkeypatch.setenv("VOICEINPUT_LOG_MAX_FILE_MB", "120")
    monkeypatch.setenv("VOICEINPUT_HOTKEY_DEBOUNCE_MS", "300")
    monkeypatch.setenv("VOICEINPUT_TRANSCRIPT_DEDUPE_WINDOW_MS", "1500")

    cfg = AppConfig.from_env()

    assert cfg.sample_rate == 22050
    assert cfg.silence_timeout_sec == 2.5
    assert cfg.stt_backend == "deepgram"
    assert cfg.deepgram_api_key == "abc"
    assert cfg.log_max_file_mb == 120
    assert cfg.hotkey_debounce_ms == 300
    assert cfg.transcript_dedupe_window_ms == 1500


def test_config_reads_dotenv_when_process_env_missing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "VOICEINPUT_STT_BACKEND=deepgram",
                "DEEPGRAM_API_KEY=from-dotenv",
                "VOICEINPUT_LOG_LEVEL=debug",
                "VOICEINPUT_LOG_MAX_FILE_MB=80",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOICEINPUT_STT_BACKEND", raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    monkeypatch.delenv("VOICEINPUT_LOG_LEVEL", raising=False)

    cfg = AppConfig.from_env()

    assert cfg.stt_backend == "deepgram"
    assert cfg.deepgram_api_key == "from-dotenv"
    assert cfg.log_level == "DEBUG"
    assert cfg.log_max_file_mb == 80
