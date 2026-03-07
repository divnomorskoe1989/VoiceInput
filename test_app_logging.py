from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app_logging import configure_logging


def test_configure_logging_uses_rotating_file_handler(tmp_path: Path):
    log_file = tmp_path / "voice_input_recovered.log"
    configure_logging(level="INFO", log_file=log_file, max_file_mb=1, backup_count=1)

    logging.getLogger("test").info("hello")

    handlers = logging.getLogger().handlers
    rotating = [h for h in handlers if isinstance(h, RotatingFileHandler)]

    assert rotating, "Expected at least one RotatingFileHandler"
    assert rotating[0].maxBytes == 1 * 1024 * 1024
    assert rotating[0].backupCount == 1
    assert log_file.exists()
