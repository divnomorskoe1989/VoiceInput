from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def _read_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _read_float(value: str | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass(slots=True)
class AppConfig:
    sample_rate: int = 16000
    chunk_size: int = 1024
    ring_buffer_chunks: int = 256
    silence_timeout_sec: float = 10.0
    silence_rms_threshold: float = 300.0
    stt_backend: str = "deepgram"
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-2"
    deepgram_language: str = "ru"
    interim_results: bool = True
    interim_insert_enabled: bool = True
    smart_format: bool = True
    log_level: str = "INFO"
    log_max_file_mb: int = 100
    log_backup_count: int = 1
    insertion_settle_delay_ms: int = 50
    session_mode: str = "realtime"
    hotkey: str = "ctrl+win"
    hotkey_debounce_ms: int = 220
    transcript_dedupe_window_ms: int = 900
    microphone_enabled: bool = False
    microphone_device: str = ""
    deepgram_endpointing_ms: int = 250

    @classmethod
    def from_env(cls) -> "AppConfig":
        dotenv = _parse_dotenv(Path(".env"))

        def raw(name: str) -> str | None:
            if name in os.environ:
                return os.environ[name]
            return dotenv.get(name)

        return cls(
            sample_rate=_read_int(raw("VOICEINPUT_SAMPLE_RATE"), 16000),
            chunk_size=_read_int(raw("VOICEINPUT_CHUNK_SIZE"), 1024),
            ring_buffer_chunks=_read_int(raw("VOICEINPUT_RING_BUFFER_CHUNKS"), 256),
            silence_timeout_sec=_read_float(raw("VOICEINPUT_SILENCE_TIMEOUT_SEC"), 10.0),
            silence_rms_threshold=_read_float(raw("VOICEINPUT_SILENCE_RMS_THRESHOLD"), 300.0),
            stt_backend=(raw("VOICEINPUT_STT_BACKEND") or "deepgram").strip().lower() or "deepgram",
            deepgram_api_key=(raw("DEEPGRAM_API_KEY") or "").strip(),
            deepgram_model=(raw("VOICEINPUT_DEEPGRAM_MODEL") or "nova-2").strip() or "nova-2",
            deepgram_language=(raw("VOICEINPUT_DEEPGRAM_LANGUAGE") or "ru").strip() or "ru",
            interim_results=_read_bool(raw("VOICEINPUT_INTERIM_RESULTS"), True),
            interim_insert_enabled=_read_bool(raw("VOICEINPUT_INTERIM_INSERT_ENABLED"), True),
            smart_format=_read_bool(raw("VOICEINPUT_SMART_FORMAT"), True),
            log_level=(raw("VOICEINPUT_LOG_LEVEL") or "INFO").upper(),
            log_max_file_mb=_read_int(raw("VOICEINPUT_LOG_MAX_FILE_MB"), 100),
            log_backup_count=_read_int(raw("VOICEINPUT_LOG_BACKUP_COUNT"), 1),
            insertion_settle_delay_ms=_read_int(raw("VOICEINPUT_INSERTION_SETTLE_DELAY_MS"), 50),
            session_mode=(raw("VOICEINPUT_SESSION_MODE") or "realtime").strip().lower() or "realtime",
            hotkey=(raw("VOICEINPUT_HOTKEY") or "ctrl+win").strip().lower() or "ctrl+win",
            hotkey_debounce_ms=_read_int(raw("VOICEINPUT_HOTKEY_DEBOUNCE_MS"), 220),
            transcript_dedupe_window_ms=_read_int(raw("VOICEINPUT_TRANSCRIPT_DEDUPE_WINDOW_MS"), 900),
            microphone_enabled=_read_bool(raw("VOICEINPUT_MICROPHONE_ENABLED"), False),
            microphone_device=(raw("VOICEINPUT_MICROPHONE_DEVICE") or "").strip(),
            deepgram_endpointing_ms=_read_int(raw("VOICEINPUT_DEEPGRAM_ENDPOINTING_MS"), 250),
        )


def detect_window_hint(window_title: str) -> str:
    normalized = (window_title or "").lower()
    if not normalized:
        return "default"
    if any(token in normalized for token in ("terminal", "cmd", "powershell", "bash", "claude code")):
        return "terminal"
    if any(token in normalized for token in ("qt", "pycharm", "vscode", "telegram")):
        return "qt"
    return "default"
