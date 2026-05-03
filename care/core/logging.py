"""PII-redacting logger.

`PIIRedactingFilter` strips obvious PII shapes from log records before
they hit a handler. This is a defensive last-line filter; primary PII
handling is in `care/pii/`.

Logs MUST never carry raw PII.
"""
from __future__ import annotations

import logging
import re

# Pattern, replacement. Recall over precision: prefer to over-redact.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b"), "[PHONE_NUMBER]"),
    (re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), "[VIN]"),
]


class PIIRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        for pattern, replacement in _PATTERNS:
            message = pattern.sub(replacement, message)
        record.msg = message
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Attach a stream handler with the PII-redacting filter to the root logger."""
    root = logging.getLogger()
    root.setLevel(level)

    pii_filter = PIIRedactingFilter()

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        handler.addFilter(pii_filter)
        root.addHandler(handler)
        return

    # Re-import or re-config: ensure existing handlers also redact.
    for handler in root.handlers:
        if not any(isinstance(f, PIIRedactingFilter) for f in handler.filters):
            handler.addFilter(pii_filter)


def configure_logging_for_frozen(
    *,
    level: int = logging.INFO,
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
) -> None:
    """Add a rotating-file handler under ``user_data_root()/logs``.

    Phase 15.4 — frozen builds run from Program Files / a Start menu
    shortcut where stdout/stderr are not visible to the operator. We
    keep the stderr handler too (so a developer attaching a console
    still sees output) but ALSO append a rotating log file under the
    user-data tree so post-mortem support is possible.

    Idempotent: safe to call multiple times. Defaults to 5 × 5 MB
    files, then the oldest is dropped.
    """
    from logging.handlers import RotatingFileHandler

    from .runtime_paths import logs_dir

    log_path = logs_dir() / "care.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    pii_filter = PIIRedactingFilter()

    # Don't attach more than one rotating handler if we're called twice.
    for h in root.handlers:
        if isinstance(h, RotatingFileHandler):
            return

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    file_handler.addFilter(pii_filter)
    root.addHandler(file_handler)
    root.setLevel(level)
