from __future__ import annotations

import ctypes
import ctypes.wintypes
import logging
import os
import sys
import time
from typing import Callable, Dict, List

from config import detect_window_hint
from contracts import InsertResult


StrategyHandler = Callable[[str], bool]


class TextInserter:
    def __init__(
        self,
        strategy_handlers: Dict[str, StrategyHandler] | None = None,
        settle_delay_ms: int = 50,
        enable_system_insertion: bool = True,
    ) -> None:
        self._logger = logging.getLogger("TextInserter")
        self._strategy_handlers = strategy_handlers or {}
        self._settle_delay_sec = max(0, int(settle_delay_ms)) / 1000.0
        self._enable_system_insertion = bool(enable_system_insertion) and ("PYTEST_CURRENT_TEST" not in os.environ)
        self._chains: Dict[str, List[str]] = {
            "terminal": ["type_direct"],
            "qt": ["ctrl_v"],
            "default": ["ctrl_v", "type_direct"],
        }
        self._keyboard = None
        self._clipboard_format_unicode = 13  # CF_UNICODETEXT
        self._gmem_moveable = 0x0002

        if self._enable_system_insertion and os.name == "nt":
            try:
                from pynput.keyboard import Controller
                self._keyboard = Controller()
            except Exception:
                self._logger.exception("Failed to initialize pynput keyboard controller.")

            # Pre-load Win32 functions with proper argtypes/restype for reliability
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32

            self._user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
            self._user32.OpenClipboard.restype = ctypes.wintypes.BOOL
            self._user32.CloseClipboard.argtypes = []
            self._user32.CloseClipboard.restype = ctypes.wintypes.BOOL
            self._user32.EmptyClipboard.argtypes = []
            self._user32.EmptyClipboard.restype = ctypes.wintypes.BOOL
            self._user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
            self._user32.SetClipboardData.restype = ctypes.wintypes.HANDLE
            self._user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
            self._user32.GetClipboardData.restype = ctypes.wintypes.HANDLE
            self._user32.IsClipboardFormatAvailable.argtypes = [ctypes.wintypes.UINT]
            self._user32.IsClipboardFormatAvailable.restype = ctypes.wintypes.BOOL
            self._user32.GetForegroundWindow.argtypes = []
            self._user32.GetForegroundWindow.restype = ctypes.wintypes.HWND

            self._kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
            self._kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
            self._kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
            self._kernel32.GlobalLock.restype = ctypes.c_void_p
            self._kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
            self._kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
            self._kernel32.GlobalFree.argtypes = [ctypes.wintypes.HGLOBAL]
            self._kernel32.GlobalFree.restype = ctypes.wintypes.HGLOBAL
        else:
            self._user32 = None
            self._kernel32 = None

    def _foreground_window_context(self) -> tuple[str, str]:
        if self._user32 is None:
            return "", ""
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        title_buffer = ctypes.create_unicode_buffer(512)
        class_buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        self._user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        return title_buffer.value.strip(), class_buffer.value.strip()

    def _open_clipboard(self) -> bool:
        """Open clipboard with fast retry (3 attempts, 5ms apart)."""
        if self._user32 is None:
            return False
        for _ in range(3):
            if self._user32.OpenClipboard(None):
                return True
            time.sleep(0.005)
        return False

    def _close_clipboard(self) -> None:
        if self._user32 is not None:
            self._user32.CloseClipboard()

    def _set_clipboard_text(self, text: str) -> bool:
        """Set clipboard text using Win32 API directly. Fast path, no powershell."""
        if self._user32 is None or self._kernel32 is None:
            return False
        if not self._open_clipboard():
            self._logger.debug("Clipboard open failed after retries.")
            return False
        handle = None
        try:
            self._user32.EmptyClipboard()
            # Encode as UTF-16LE with null terminator
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            data_size = len(encoded)
            handle = self._kernel32.GlobalAlloc(self._gmem_moveable, data_size)
            if not handle:
                return False
            pointer = self._kernel32.GlobalLock(handle)
            if not pointer:
                self._kernel32.GlobalFree(handle)
                return False
            try:
                ctypes.memmove(pointer, encoded, data_size)
            finally:
                self._kernel32.GlobalUnlock(handle)

            result = self._user32.SetClipboardData(self._clipboard_format_unicode, handle)
            if not result:
                self._kernel32.GlobalFree(handle)
                return False
            handle = None  # ownership transferred
            return True
        finally:
            self._close_clipboard()
            if handle:
                self._kernel32.GlobalFree(handle)

    def _send_shortcut(self, strategy: str) -> bool:
        if self._keyboard is None:
            return False
        try:
            from pynput.keyboard import Key
            if strategy in {"ctrl_v", "send_input_ctrl_v", "wm_paste"}:
                self._keyboard.press(Key.ctrl)
                self._keyboard.press("v")
                self._keyboard.release("v")
                self._keyboard.release(Key.ctrl)
                return True
            if strategy == "shift_insert":
                self._keyboard.press(Key.shift)
                self._keyboard.press(Key.insert)
                self._keyboard.release(Key.insert)
                self._keyboard.release(Key.shift)
                return True
            return False
        except Exception:
            self._logger.exception("Failed to send shortcut for strategy %s.", strategy)
            return False

    def _type_text(self, text: str) -> bool:
        if self._keyboard is None:
            return False
        try:
            self._keyboard.type(text)
            return True
        except Exception:
            self._logger.exception("Failed to type text fallback.")
            return False

    def _paste_with_strategy(self, strategy: str, text: str) -> bool:
        if not self._enable_system_insertion or os.name != "nt":
            return False

        if not self._set_clipboard_text(text):
            self._logger.debug("Clipboard write failed for strategy %s.", strategy)
            return False

        sent = self._send_shortcut(strategy)
        if self._settle_delay_sec > 0:
            time.sleep(self._settle_delay_sec)
        return sent

    def _execute_strategy(self, strategy: str, text: str, window_hint: str) -> bool:
        handler = self._strategy_handlers.get(strategy)
        if handler is None:
            if strategy == "type_direct":
                return self._type_text(text)
            if strategy in {"ctrl_v", "shift_insert", "send_input_ctrl_v", "wm_paste"}:
                if self._paste_with_strategy(strategy, text):
                    return True
                return self._type_text(text)
            return False
        return bool(handler(text))

    def insert_text(
        self,
        text: str,
        window_title: str = "",
        window_class: str = "",
    ) -> InsertResult:
        started = time.perf_counter()
        if not text:
            return InsertResult(strategy="none", executed=False, success=False, latency_ms=0.0)

        if not window_title and not window_class:
            window_title, window_class = self._foreground_window_context()

        window_hint = detect_window_hint(window_title or window_class)
        chain = self._chains.get(window_hint, self._chains["default"])

        self._logger.info(
            "INSERT_TARGET | hint=%s | title=%r | class=%r | text_len=%s",
            window_hint,
            window_title,
            window_class,
            len(text),
        )

        for strategy in chain:
            ok = self._execute_strategy(strategy, text, window_hint=window_hint)
            latency_ms = (time.perf_counter() - started) * 1000
            if ok:
                return InsertResult(
                    strategy=strategy,
                    executed=True,
                    success=True,
                    clipboard_consumed=False,
                    latency_ms=latency_ms,
                )

        latency_ms = (time.perf_counter() - started) * 1000
        return InsertResult(
            strategy=chain[-1],
            executed=True,
            success=False,
            clipboard_consumed=False,
            latency_ms=latency_ms,
        )
