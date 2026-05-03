"""Safety helpers shared by every LLM/VLM provider.

These functions are the structural guarantees the plugin layer relies
on. Each is a pure utility — no external state, no vendor SDK imports.

- :func:`is_loopback_url` — decides whether an HTTP endpoint URL
  points at the local host. Anything else is "remote" and requires
  explicit ``allow_non_loopback=True`` in the per-provider config.
- :func:`redact_secrets` — strips API-key-shaped fields from any
  dict before it enters a manifest, log, or HTTP response.
- :func:`reject_in_offline_mode` — uniform fail-closed for any
  cloud provider when the global offline guard is on.

Loopback hosts are restrictive on purpose: ``0.0.0.0`` is **NOT**
loopback (it binds to every interface; from the kernel's point of
view it's reachable from anywhere).
"""
from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse

from ..core.errors import ConfigError, OfflineGuardError

LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
})

_SECRET_KEY_PATTERN = re.compile(
    r"(?:^|_)(?:api[_-]?key|key|token|secret|password|auth|credential|bearer)$",
    re.IGNORECASE,
)
_REDACTED = "***REDACTED***"


def is_loopback_url(url: str | None) -> bool:
    """Return True iff ``url`` resolves to a recognised loopback host.

    Empty / None / unparseable URLs return False (rejected by callers).
    The check is host-only — port doesn't matter. ``0.0.0.0`` is
    explicitly rejected: it is *not* loopback in the kernel's sense.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except (ValueError, TypeError):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return host in LOOPBACK_HOSTS


def redact_secrets(value: Any, *, extra_keys: Iterable[str] = ()) -> Any:
    """Recursively strip API-key-shaped fields from ``value``.

    Used by every provider's :py:meth:`get_model_manifest` to ensure
    that no manifest, log line, or API response leaks an API key,
    bearer token, password, or auth header. Keys whose name matches
    ``_SECRET_KEY_PATTERN`` (or any caller-supplied ``extra_keys``)
    are replaced with ``"***REDACTED***"``.

    Lists and tuples are walked recursively. Other types are returned
    untouched (the redactor never coerces unknown types).
    """
    extra_lower = {k.lower() for k in extra_keys}
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_str = str(k)
            if (
                _SECRET_KEY_PATTERN.search(key_str)
                or key_str.lower() in extra_lower
            ):
                # Preserve the bare presence/absence signal so an
                # auditor can see "yes, an api_key is configured" —
                # but never the value.
                out[k] = _REDACTED if v not in (None, "", []) else None
            else:
                out[k] = redact_secrets(v, extra_keys=extra_keys)
        return out
    if isinstance(value, list):
        return [redact_secrets(item, extra_keys=extra_keys) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, extra_keys=extra_keys) for item in value)
    return value


def reject_in_offline_mode(
    provider_name: str,
    *,
    requires_network: bool,
    offline_enabled: bool,
) -> None:
    """Raise OfflineGuardError when a network-requiring provider is
    asked to load while the global offline guard is on. Cloud
    providers call this from their ``load()`` so the rejection is
    uniform across vendors."""
    if requires_network and offline_enabled:
        raise OfflineGuardError(
            f"Provider {provider_name!r} requires network access, but "
            "offline.enabled is true. Cloud providers cannot run in "
            "offline mode."
        )


def assert_loopback_or_explicit(
    provider_name: str,
    *,
    endpoint_url: str | None,
    allow_non_loopback: bool,
    offline_enabled: bool,
) -> None:
    """Validate a local-LLM provider's endpoint URL.

    Local providers (Ollama, vLLM, llama.cpp, LM Studio) talk to a
    server. The URL is "local" only if it points at loopback. A
    non-loopback URL is treated as remote: it must be explicitly
    permitted via ``allow_non_loopback=True``, AND offline mode must
    be off. Both checks are required — flipping either alone is not
    enough.
    """
    if not endpoint_url:
        raise ConfigError(
            f"Provider {provider_name!r} requires endpoint_url"
        )
    if is_loopback_url(endpoint_url):
        return
    if not allow_non_loopback:
        raise ConfigError(
            f"Provider {provider_name!r} endpoint_url={endpoint_url!r} "
            "is not loopback. Set allow_non_loopback=true to permit "
            "remote endpoints."
        )
    if offline_enabled:
        raise OfflineGuardError(
            f"Provider {provider_name!r} endpoint_url={endpoint_url!r} "
            "is non-loopback; offline.enabled is true so the request "
            "is blocked."
        )
