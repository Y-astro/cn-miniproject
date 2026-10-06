"""Structured logging utility with file/console output and rate limiting."""

import logging
import sys
import time
from pathlib import Path
from typing import Dict, Optional


class RateLimitedLogger:
    """Wrapper that rate-limits high-frequency log messages by key."""

    def __init__(self, logger: logging.Logger, window_sec: float = 1.0, max_burst: int = 5):
        self.logger = logger
        self.window_sec = window_sec
        self.max_burst = max_burst
        self._counts: Dict[str, int] = {}
        self._window_starts: Dict[str, float] = {}

    def should_log(self, key: str) -> bool:
        now = time.monotonic()
        start = self._window_starts.get(key, 0.0)
        if now - start >= self.window_sec:
            self._window_starts[key] = now
            self._counts[key] = 1
            return True

        count = self._counts.get(key, 0)
        if count < self.max_burst:
            self._counts[key] = count + 1
            return True
        return False

    def debug(self, msg: str, *args, **kwargs) -> None:
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        self.logger.error(msg, *args, **kwargs)

    def rate_limited_warning(self, key: str, msg: str) -> None:
        if self.should_log(key):
            self.logger.warning(msg)

    def rate_limited_error(self, key: str, msg: str) -> None:
        if self.should_log(key):
            self.logger.error(msg)


def setup_logger(
    name: str = "health_monitor",
    level: str = "INFO",
    log_file: Optional[str] = None,
    console: bool = True,
) -> RateLimitedLogger:
    """Sets up a logger with standard formatting, file output, and rate limiting."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(path))
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return RateLimitedLogger(logger)
