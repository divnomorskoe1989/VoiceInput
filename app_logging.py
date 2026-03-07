from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_FORMAT = "%(asctime)s | %(process)d | %(name)s | %(levelname)s | %(message)s"


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    max_file_mb: int = 100,
    backup_count: int = 1,
) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Reconfigure handlers deterministically to avoid duplicates.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(DEFAULT_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_file is None:
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1, int(max_file_mb)) * 1024 * 1024
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    root_logger.info(
        "LOG_CONFIG | level=%s | file=%s | rotate_max_bytes=%s | backup_count=%s",
        level.upper(),
        log_file,
        max_bytes,
        max(1, int(backup_count)),
    )
