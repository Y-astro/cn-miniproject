"""Structured logging utility with file/console output and rate limiting."""

# Import built-in logging module for flexible event logging
import logging
# Import sys to access standard output stream for console logging
import sys
# Import time for monotonic timestamps used in rate-limiting calculations
import time
# Import Path from pathlib for safe filesystem operations
from pathlib import Path
# Import typing annotations for static type safety
from typing import Dict, Optional


# Wrapper class that wraps a Python logger and suppresses repetitive log floods
class RateLimitedLogger:
    """Wrapper that rate-limits high-frequency log messages by key."""

    # Initialize rate limiter with reference logger, sliding window size, and burst limit
    def __init__(self, logger: logging.Logger, window_sec: float = 1.0, max_burst: int = 5):
        # Store underlying standard logging.Logger instance
        self.logger = logger
        # Duration in seconds of the rate-limiting sliding window
        self.window_sec = window_sec
        # Maximum allowed log messages per key within one window duration
        self.max_burst = max_burst
        # Dictionary tracking log counts per message key: {key: count}
        self._counts: Dict[str, int] = {}
        # Dictionary tracking window start timestamps per key: {key: timestamp}
        self._window_starts: Dict[str, float] = {}

    # Check whether a log message identified by 'key' should be emitted or suppressed
    def should_log(self, key: str) -> bool:
        # Get current monotonic time (guaranteed never to jump backward)
        now = time.monotonic()
        # Retrieve the timestamp when the current time window began for this key
        start = self._window_starts.get(key, 0.0)
        # If elapsed time exceeds window duration, reset the window
        if now - start >= self.window_sec:
            # Update start of window to current timestamp
            self._window_starts[key] = now
            # Reset message counter for this key to 1
            self._counts[key] = 1
            # Allow this log message through
            return True

        # Retrieve current count of logs emitted in the active window
        count = self._counts.get(key, 0)
        # Check if current count has not yet reached maximum burst ceiling
        if count < self.max_burst:
            # Increment message counter for this key
            self._counts[key] = count + 1
            # Allow this log message through
            return True
        # Ceil reached: suppress message to avoid log spam and I/O bottlenecks
        return False

    # Forward debug messages directly to underlying logger
    def debug(self, msg: str, *args, **kwargs) -> None:
        # Emit debug level message
        self.logger.debug(msg, *args, **kwargs)

    # Forward informational messages directly to underlying logger
    def info(self, msg: str, *args, **kwargs) -> None:
        # Emit info level message
        self.logger.info(msg, *args, **kwargs)

    # Forward warning messages directly to underlying logger
    def warning(self, msg: str, *args, **kwargs) -> None:
        # Emit warning level message
        self.logger.warning(msg, *args, **kwargs)

    # Forward error messages directly to underlying logger
    def error(self, msg: str, *args, **kwargs) -> None:
        # Emit error level message
        self.logger.error(msg, *args, **kwargs)

    # Emit warning message only if the rate limiter permits it for this key
    def rate_limited_warning(self, key: str, msg: str) -> None:
        # Check rate limit permission
        if self.should_log(key):
            # Emit warning to logger if permitted
            self.logger.warning(msg)

    # Emit error message only if the rate limiter permits it for this key
    def rate_limited_error(self, key: str, msg: str) -> None:
        # Check rate limit permission
        if self.should_log(key):
            # Emit error to logger if permitted
            self.logger.error(msg)


# Factory function to configure and return a ready-to-use RateLimitedLogger instance
def setup_logger(
    name: str = "health_monitor",
    level: str = "INFO",
    log_file: Optional[str] = None,
    console: bool = True,
) -> RateLimitedLogger:
    """Sets up a logger with standard formatting, file output, and rate limiting."""
    # Obtain or create logger instance by hierarchy name
    logger = logging.getLogger(name)
    # Set the logging threshold level (DEBUG, INFO, WARNING, ERROR)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Clear any existing handlers to prevent duplicate log lines
    logger.handlers.clear()

    # Define standard uniform log entry formatting string
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # If console logging is enabled, attach stdout stream handler
    if console:
        # Create stdout handler
        console_handler = logging.StreamHandler(sys.stdout)
        # Apply standard log formatter
        console_handler.setFormatter(formatter)
        # Add console handler to logger
        logger.addHandler(console_handler)

    # If log file path is specified, attach file handler
    if log_file:
        # Convert path string to Path object
        path = Path(log_file)
        # Ensure parent directories exist before creating log file
        path.parent.mkdir(parents=True, exist_ok=True)
        # Create file logging handler targeting specified destination file
        file_handler = logging.FileHandler(str(path))
        # Apply standard log formatter to file handler
        file_handler.setFormatter(formatter)
        # Add file handler to logger
        logger.addHandler(file_handler)

    # Wrap logger with rate-limiting decorator and return
    return RateLimitedLogger(logger)
