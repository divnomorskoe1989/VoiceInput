from __future__ import annotations

import argparse
import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Iterable

from app_logging import configure_logging
from audio_recorder import AudioRecorder
from config import AppConfig
from keyboard_handler import HotkeyHandler
from sound_notifier import SoundNotifier
from stt_client import MockSTTClient
from stt_router import build_stt_client
from text_inserter import TextInserter
from tray_manager import TrayManager
from voice_input_app import VoiceInputApp


def _acquire_listener_single_instance() -> tuple[bool, Callable[[], None]]:
    """Ensure only one live hotkey listener is active at a time."""
    lock_name = "VoiceInputRecoveredLiveListener"
    logger = logging.getLogger("Main")

    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateMutexW(None, False, f"Local\\{lock_name}")
            if not handle:
                logger.error("LISTENER_LOCK | event=create_failed | name=%s", lock_name)
                return False, (lambda: None)
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                kernel32.CloseHandle(handle)
                logger.warning("LISTENER_LOCK | event=already_exists | name=%s", lock_name)
                return False, (lambda: None)

            logger.info("LISTENER_LOCK | event=acquired | name=%s", lock_name)

            def release() -> None:
                try:
                    kernel32.CloseHandle(handle)
                except Exception:
                    logger.exception("LISTENER_LOCK | event=release_failed | name=%s", lock_name)
                else:
                    logger.info("LISTENER_LOCK | event=released | name=%s", lock_name)

            return True, release
        except Exception:
            logger.exception("LISTENER_LOCK | event=acquire_failed | name=%s", lock_name)
            return False, (lambda: None)

    lock_path = Path(tempfile.gettempdir()) / f"{lock_name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        logger.info("LISTENER_LOCK | event=acquired_file | path=%s", lock_path)

        def release() -> None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                lock_path.unlink(missing_ok=True)
            except OSError:
                pass
            logger.info("LISTENER_LOCK | event=released_file | path=%s", lock_path)

        return True, release
    except FileExistsError:
        logger.warning("LISTENER_LOCK | event=already_exists_file | path=%s", lock_path)
        return False, (lambda: None)
    except Exception:
        logger.exception("LISTENER_LOCK | event=acquire_file_failed | path=%s", lock_path)
        return False, (lambda: None)


def build_app(config: AppConfig) -> VoiceInputApp:
    recorder = AudioRecorder(
        sample_rate=config.sample_rate,
        chunk_size=config.chunk_size,
        ring_buffer_chunks=config.ring_buffer_chunks,
        silence_timeout_sec=config.silence_timeout_sec,
        silence_rms_threshold=config.silence_rms_threshold,
        microphone_enabled=config.microphone_enabled,
        microphone_device=config.microphone_device,
    )
    stt_client = build_stt_client(config)
    inserter = TextInserter(
        settle_delay_ms=config.insertion_settle_delay_ms,
        enable_system_insertion=("PYTEST_CURRENT_TEST" not in os.environ),
    )
    tray = TrayManager()
    notifier = SoundNotifier()
    return VoiceInputApp(config, recorder, stt_client, inserter, tray, notifier)


def build_hotkey_handler(config: AppConfig, app: VoiceInputApp) -> HotkeyHandler:
    handler = HotkeyHandler(
        hotkey=config.hotkey,
        debounce_ms=config.hotkey_debounce_ms,
    )
    handler.set_callback(app.toggle_recording)
    logging.getLogger("Main").info(
        "HOTKEY_HANDLER_BOUND | hotkey=%s | debounce_ms=%s",
        config.hotkey,
        config.hotkey_debounce_ms,
    )
    return handler


def _to_pynput_hotkey(hotkey: str) -> str:
    mapping = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "windows": "<cmd>",
        "cmd": "<cmd>",
        "super": "<cmd>",
    }
    tokens = [token.strip().lower() for token in hotkey.split("+") if token.strip()]
    converted = [mapping.get(token, token) for token in tokens]
    return "+".join(converted)


def _hotkey_tokens(hotkey: str) -> list[str]:
    return [token.strip().lower() for token in hotkey.split("+") if token.strip()]


def _modifier_aliases() -> dict[str, set[str]]:
    return {
        "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
        "control": {"ctrl", "ctrl_l", "ctrl_r"},
        "alt": {"alt", "alt_l", "alt_r"},
        "shift": {"shift", "shift_l", "shift_r"},
        "win": {"cmd", "cmd_l", "cmd_r"},
        "windows": {"cmd", "cmd_l", "cmd_r"},
        "cmd": {"cmd", "cmd_l", "cmd_r"},
        "super": {"cmd", "cmd_l", "cmd_r"},
    }


def _is_modifier_only_hotkey(hotkey: str) -> bool:
    aliases = _modifier_aliases()
    tokens = _hotkey_tokens(hotkey)
    return bool(tokens) and all(token in aliases for token in tokens)


def _modifiers_match_hotkey(pressed_names: set[str], hotkey: str) -> bool:
    aliases = _modifier_aliases()
    for token in _hotkey_tokens(hotkey):
        if token not in aliases:
            return False
        if not (pressed_names & aliases[token]):
            return False
    return True


def run_hotkey_listener(handler: HotkeyHandler, hotkey: str, exit_key: str = "esc") -> int:
    try:
        from pynput import keyboard as pynput_keyboard
    except ImportError:
        logging.getLogger("Main").error("HOTKEY_LISTENER | pynput is not installed")
        print("Runtime error: pynput is not installed. Install it to use --listen-hotkey mode.")
        return 3

    hotkey_text = _to_pynput_hotkey(hotkey)
    logger = logging.getLogger("Main")
    modifier_only_mode = _is_modifier_only_hotkey(hotkey)
    logger.info(
        "HOTKEY_LISTENER | event=start | hotkey=%s | parsed=%s | exit_key=%s | modifier_only=%s",
        hotkey,
        hotkey_text,
        exit_key,
        modifier_only_mode,
    )

    def on_activate() -> None:
        handler.trigger()

    hotkey_runtime = None
    if not modifier_only_mode:
        parsed = pynput_keyboard.HotKey.parse(hotkey_text)
        hotkey_runtime = pynput_keyboard.HotKey(parsed, on_activate)

    pressed_names: set[str] = set()
    modifier_chord_fired = False

    def _normalize_exit_key(names: Iterable[str]) -> str:
        for name in names:
            clean = (name or "").strip().lower()
            if clean:
                return clean
        return "esc"

    exit_key_normalized = _normalize_exit_key([exit_key])

    def _key_name(raw_key) -> str:
        if hasattr(raw_key, "name") and raw_key.name:
            return str(raw_key.name).lower()
        raw = str(raw_key).replace("Key.", "").lower()
        if len(raw) >= 3 and raw[0] == "'" and raw[-1] == "'":
            return raw[1:-1]
        return raw

    def on_press(key) -> None:
        nonlocal modifier_chord_fired
        key_name = _key_name(key)
        pressed_names.add(key_name)

        if hotkey_runtime is not None:
            hotkey_runtime.press(listener.canonical(key))

        if modifier_only_mode and not modifier_chord_fired and _modifiers_match_hotkey(pressed_names, hotkey):
            logger.info("HOTKEY_LISTENER | event=modifier_chord_detected | hotkey=%s", hotkey)
            handler.trigger()
            modifier_chord_fired = True

    def on_release(key):
        nonlocal modifier_chord_fired
        key_name = _key_name(key)

        if hotkey_runtime is not None:
            hotkey_runtime.release(listener.canonical(key))

        if key_name in pressed_names:
            pressed_names.remove(key_name)
        if modifier_only_mode and not _modifiers_match_hotkey(pressed_names, hotkey):
            modifier_chord_fired = False

        return None

    print(
        f"Hotkey listener started. Press {hotkey} to toggle recording. "
        f"Exit via system tray icon."
    )
    with pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()
    logger.info("HOTKEY_LISTENER | event=stopped")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovered VoiceInput launcher")
    parser.add_argument("--backend", default=None, help="Override STT backend: mock/local/deepgram")
    parser.add_argument("--once", action="store_true", help="Run one simulated recording session")
    parser.add_argument("--simulate-text", default="recovered voice input", help="Final transcript for --once")
    parser.add_argument(
        "--listen-hotkey",
        action="store_true",
        help="Run runtime hotkey listener (Ctrl+Win by default, Esc to exit).",
    )
    parser.add_argument("--exit-key", default="esc", help="Exit key for --listen-hotkey mode.")
    args = parser.parse_args()

    config = AppConfig.from_env()
    if args.backend:
        config.stt_backend = args.backend.strip().lower()
    if args.listen_hotkey:
        config.microphone_enabled = True

    configure_logging(
        level=config.log_level,
        log_file=Path("tmp") / "voice_input_recovered.log",
        max_file_mb=config.log_max_file_mb,
        backup_count=config.log_backup_count,
    )

    try:
        app = build_app(config)
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 2

    hotkey_handler = build_hotkey_handler(config, app)

    if args.listen_hotkey:
        acquired, release = _acquire_listener_single_instance()
        if not acquired:
            logging.getLogger("Main").error(
                "RUNTIME_MODE | listen_hotkey=true | duplicate_listener=true | pid=%s",
                os.getpid(),
            )
            print("Another VoiceInput listener is already running. Press ESC in the existing listener window first.")
            return 4

        logging.getLogger("Main").info(
            "RUNTIME_MODE | listen_hotkey=true | stt_backend=%s | microphone_enabled=%s | hotkey=%s",
            config.stt_backend,
            config.microphone_enabled,
            config.hotkey,
        )

        # Start system tray icon; Exit from tray kills the process
        def _tray_exit() -> None:
            logging.getLogger("Main").info("TRAY_EXIT | event=exit_from_tray")
            tray.stop()
            release()
            os._exit(0)

        tray = app.tray_manager
        tray._on_exit = _tray_exit
        tray.start()

        try:
            return run_hotkey_listener(hotkey_handler, config.hotkey, exit_key=args.exit_key)
        finally:
            tray.stop()
            release()

    if not args.once:
        print("VoiceInput recovered build is ready. Use --once for a simulated session.")
        return 0

    app.set_window_context(title="Recovered Terminal", class_name="CASCADIA_HOSTING_WINDOW_CLASS")
    try:
        app.start_recording()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 2

    if isinstance(app.stt_client, MockSTTClient):
        app.stt_client.queue_event(args.simulate_text, is_final=True)

    for _ in range(6):
        app.add_audio_chunk(b"\x00\x01" * 256, rms=900.0)

    stats = app.stop_recording()
    print(
        "Session finished: "
        f"duration={stats.duration_sec:.2f}s fragments={stats.fragments_inserted} chars={stats.chars_inserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
