import inspect
import logging
import os
import sys

from loguru import logger


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists.
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find caller from where originated the logged message.
        frame, depth = inspect.currentframe(), 0
        while frame:
            filename = frame.f_code.co_filename
            is_logging = filename == logging.__file__
            is_frozen = "importlib" in filename and "_bootstrap" in filename
            if depth > 0 and not (is_logging or is_frozen):
                break
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


class LogConfig:
    def __init__(
        self,
        level: str | None = None,
        log_path: str | None = None,
    ):
        self.level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
        self.log_path = log_path or os.getenv("LOG_PATH")

    def configure(self) -> None:
        logger.remove()
        logger.add(sys.stderr, level=self.level)

        if self.log_path:
            logger.add(
                self.log_path,
                level=self.level,
                rotation="100 MB",
                retention="5 days",
                encoding="utf-8",
            )

        logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
