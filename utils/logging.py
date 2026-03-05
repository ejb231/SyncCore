"""Logging setup: Rich console, rotating file handler, WebSocket buffer."""

from __future__ import annotations

import collections
import logging
from pathlib import Path
from typing import Callable

from rich.logging import RichHandler

_configured = False
_ws_handler: BufferedWebSocketHandler | None = None


class BufferedWebSocketHandler(logging.Handler):
    """Ring-buffer handler that also pushes entries to WebSocket clients."""

    def __init__(self, maxlen: int = 1000) -> None:
        super().__init__()
        self.buffer: collections.deque[dict] = collections.deque(maxlen=maxlen)
        self._broadcast_cb: Callable | None = None

    def set_broadcast(self, callback: Callable) -> None:
        self._broadcast_cb = callback

    def emit(self, record: logging.LogRecord) -> None:
        entry = {
            "timestamp": record.created,
            "level": record.levelname,
            "name": record.name,
            "message": self.format(record),
        }
        self.buffer.append(entry)
        if self._broadcast_cb:
            try:
                self._broadcast_cb({"event": "log", "data": entry})
            except Exception:
                pass


def get_log_buffer(level: str | None = None) -> list[dict]:
    if _ws_handler is None:
        return []
    items = list(_ws_handler.buffer)
    if level:
        items = [e for e in items if e["level"] == level.upper()]
    return items


def setup_logging(level: str = "INFO", log_dir: str | None = None) -> None:
    """Configure root logger with console, WebSocket buffer, and optional file output."""
    global _configured, _ws_handler
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    console = RichHandler(
        rich_tracebacks=True,
        show_time=True,
        show_path=False,
        markup=True,
    )
    console.setLevel(logging.DEBUG)
    root.addHandler(console)

    _ws_handler = BufferedWebSocketHandler()
    _ws_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )
    root.addHandler(_ws_handler)

    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        fh = RotatingFileHandler(
            log_path / "sync.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        root.addHandler(fh)


def get_ws_handler() -> BufferedWebSocketHandler | None:
    return _ws_handler


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"sync.{name}")
