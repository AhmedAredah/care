"""Typed errors for care."""
from __future__ import annotations


class CAREError(Exception):
    """Base class for all errors raised by this package."""


class OfflineGuardError(CAREError):
    """Raised when offline mode detects an attempted external connection."""


class PluginNotFoundError(CAREError):
    """Raised when a registry is asked for an unregistered provider."""


class FailClosedError(CAREError):
    """Raised when the QA gate blocks an export."""


class ConfigError(CAREError):
    """Raised when configuration is missing or invalid."""


class PathTraversalError(CAREError):
    """Raised when a path attempts to escape its sandbox."""
