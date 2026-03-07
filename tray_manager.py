from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Callable

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]


def _make_icon_image(color: str = "#4CAF50", size: int = 64) -> "Image.Image":
    """Create a simple colored circle icon."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=color)
    # Small mic shape in center
    cx, cy = size // 2, size // 2
    r = size // 6
    draw.rounded_rectangle(
        [cx - r, cy - r - 4, cx + r, cy + r],
        radius=r,
        fill="white",
    )
    draw.rectangle([cx - 1, cy + r, cx + 1, cy + r + 6], fill="white")
    draw.rectangle([cx - r, cy + r + 5, cx + r, cy + r + 7], fill="white")
    return img


class AutostartManager:
    """Manage Windows autostart via Start Menu shortcut."""

    _STARTUP_DIR = Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    _SHORTCUT_NAME = "VoiceInput.vbs"

    def __init__(self) -> None:
        self._logger = logging.getLogger("AutostartManager")
        self._app_dir = Path(__file__).resolve().parent
        self._vbs_launcher = self._app_dir / "start_hidden.vbs"

    @property
    def shortcut_path(self) -> Path:
        return self._STARTUP_DIR / self._SHORTCUT_NAME

    def is_enabled(self) -> bool:
        return self.shortcut_path.exists()

    def enable(self) -> bool:
        try:
            if not self._vbs_launcher.exists():
                self._logger.error("start_hidden.vbs not found at %s", self._vbs_launcher)
                return False
            # Create a .vbs file in Startup that runs our hidden launcher
            self.shortcut_path.write_text(
                f'CreateObject("Wscript.Shell").Run """" & "{self._vbs_launcher}" & """", 0, False\n',
                encoding="utf-8",
            )
            self._logger.info("AUTOSTART | event=enabled | path=%s", self.shortcut_path)
            return True
        except Exception:
            self._logger.exception("AUTOSTART | event=enable_failed")
            return False

    def disable(self) -> bool:
        try:
            if self.shortcut_path.exists():
                self.shortcut_path.unlink()
            self._logger.info("AUTOSTART | event=disabled | path=%s", self.shortcut_path)
            return True
        except Exception:
            self._logger.exception("AUTOSTART | event=disable_failed")
            return False

    def toggle(self) -> bool:
        if self.is_enabled():
            self.disable()
            return False
        else:
            self.enable()
            return True


class TrayManager:
    def __init__(self, on_exit: Callable[[], None] | None = None) -> None:
        self._recording = False
        self._logger = logging.getLogger("TrayManager")
        self._icon: pystray.Icon | None = None
        self._on_exit = on_exit
        self._autostart = AutostartManager()
        self._tray_thread: threading.Thread | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    def set_recording(self, value: bool) -> None:
        self._recording = bool(value)
        self._logger.debug("Tray recording state set to %s", self._recording)
        if self._icon is not None:
            try:
                color = "#F44336" if self._recording else "#4CAF50"
                self._icon.icon = _make_icon_image(color)
                status = "Recording..." if self._recording else "Ready (Ctrl+Win)"
                self._icon.title = f"VoiceInput - {status}"
            except Exception:
                self._logger.debug("Failed to update tray icon", exc_info=True)

    def _on_quit(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        self._logger.info("TRAY | event=quit_requested")
        icon.stop()
        if self._on_exit:
            self._on_exit()

    def _on_toggle_autostart(self, icon: "pystray.Icon", item: "pystray.MenuItem") -> None:
        enabled = self._autostart.toggle()
        self._logger.info("TRAY | event=autostart_toggled | enabled=%s", enabled)
        # Update menu by notifying icon
        icon.update_menu()

    def _autostart_checked(self, item: "pystray.MenuItem") -> bool:
        return self._autostart.is_enabled()

    def start(self) -> None:
        if pystray is None or Image is None:
            self._logger.warning("pystray/Pillow not available; tray icon disabled.")
            return

        icon_image = _make_icon_image("#4CAF50")
        menu = pystray.Menu(
            pystray.MenuItem("VoiceInput", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Autostart",
                self._on_toggle_autostart,
                checked=self._autostart_checked,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._on_quit),
        )
        self._icon = pystray.Icon(
            "VoiceInput",
            icon_image,
            title="VoiceInput - Ready (Ctrl+Win)",
            menu=menu,
        )

        self._tray_thread = threading.Thread(target=self._icon.run, daemon=True)
        self._tray_thread.start()
        self._logger.info("TRAY | event=started")

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        self._logger.info("TRAY | event=stopped")
