from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path


def configure_logging(log_dir: Path, debug: bool = False) -> tuple[logging.Logger, Path]:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    logger = logging.getLogger("mteam_cli")
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # StreamHandler defaults to stderr — keeps stdout pipe-clean for the
    # machine-format query commands (json/yaml/csv).
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    return logger, log_path
