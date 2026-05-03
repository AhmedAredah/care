"""YAML round-trip writer for the GUI Settings save path (Phase 13.3).

The read path (``care/core/config.py``) uses PyYAML — smaller,
faster, and we only need scalar values. The write path uses
``ruamel.yaml`` so that operator-curated comments and key ordering in
``config.yaml`` survive a round-trip from the GUI.

Three guarantees this module provides:

1. **Atomic write.** We serialise to a sibling ``.tmp`` and
   ``os.replace`` into place. A reader doing ``yaml.safe_load`` either
   sees the previous file or the new one — never a half-written one.

2. **Backup on every save.** Before overwriting we copy the existing
   file to ``config.yaml.<utc-timestamp>.bak``, then prune to the
   most recent ``MAX_BACKUPS`` entries. Operators expect to be able
   to roll back from the GUI; this is the on-disk audit trail.

3. **Comment-preserving merge.** A patch dict is applied *in place*
   on the loaded ``CommentedMap``, so untouched keys keep the comments
   that lived above / beside them in the source file.

The single :func:`save_patch` entry point glues those three together
behind a process-level lock so two simultaneous PATCH calls
serialise.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .config import DEFAULT_CONFIG_PATHS

MAX_BACKUPS: int = 10

# Single global lock for the read-modify-write cycle. The atomic
# ``os.replace`` already protects readers from torn writes; the lock
# protects two PATCH callers from racing on the same file.
_WRITE_LOCK = threading.RLock()

_BACKUP_TIMESTAMP_RE = re.compile(
    r"^(?P<stem>.+?)\.(?P<ts>\d{8}T\d{6}Z)\.bak\.(?P<ext>ya?ml)$"
)


def _make_yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = 120
    return yaml


def resolve_write_path(*, fallback_dir: Optional[Path] = None) -> Path:
    """Pick the file the GUI's Settings page writes to.

    1. The first existing path in ``DEFAULT_CONFIG_PATHS`` (matches
       what ``load_config()`` would read). In a frozen build that
       puts the user-data path first; in dev that puts cwd first.
    2. Otherwise:
       - **Frozen** → ``user_data_root()/config/config.yaml``. We can
         create the file (and parent dirs) in the user-data tree
         because that's writable; ``cwd`` typically isn't (Program
         Files / System32).
       - **Dev** → ``fallback_dir/config.yaml`` (defaults to cwd) so
         the existing behaviour is preserved.
    """
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return Path(candidate).resolve()
    from .runtime_paths import config_dir, is_frozen

    if is_frozen():
        return (config_dir() / "config.yaml").resolve()
    base = fallback_dir or Path.cwd()
    return (base / "config.yaml").resolve()


def _apply_patch_in_place(doc: Any, patch: dict[str, Any]) -> None:
    """Recursively apply ``patch`` to ``doc`` in place.

    Walks only the keys present in ``patch``. Untouched keys keep
    whatever ruamel-attached comments / ordering they had. Lists and
    scalars are replaced wholesale (matches the deep-merge semantics
    used by validation).
    """
    for key, value in patch.items():
        existing = doc.get(key) if isinstance(doc, dict) else None
        if isinstance(value, dict) and isinstance(existing, dict):
            _apply_patch_in_place(existing, value)
        else:
            doc[key] = value


def _format_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_existing(
    target: Path, *, max_backups: Optional[int] = None
) -> Optional[Path]:
    """Copy ``target`` to a timestamped sibling and prune old backups.

    Returns the new backup path, or ``None`` when the target doesn't
    exist (a fresh save with no prior file is fine — no backup needed).

    ``max_backups`` defaults to the module-level :data:`MAX_BACKUPS`
    looked up at call time, so tests can ``monkeypatch.setattr`` the
    constant without poisoning a cached default-argument binding.
    """
    if not target.exists():
        return None
    ts = _format_timestamp()
    suffix = target.suffix.lstrip(".") or "yaml"
    backup = target.with_name(f"{target.stem}.{ts}.bak.{suffix}")
    shutil.copy2(target, backup)
    _prune_backups(
        target,
        max_backups=max_backups if max_backups is not None else MAX_BACKUPS,
    )
    return backup


def _prune_backups(target: Path, *, max_backups: int) -> None:
    parent = target.parent
    if not parent.exists():
        return
    siblings: list[Path] = []
    for entry in parent.iterdir():
        if not entry.is_file():
            continue
        match = _BACKUP_TIMESTAMP_RE.match(entry.name)
        if match and match.group("stem") == target.stem:
            siblings.append(entry)
    siblings.sort(key=lambda p: p.name, reverse=True)
    for stale in siblings[max_backups:]:
        try:
            stale.unlink()
        except OSError:
            # Backup pruning is best-effort; a stale .bak is never
            # consulted by the read path.
            continue


def _atomic_replace(tmp: Path, target: Path) -> None:
    # Windows: AV scanners and lingering read handles (e.g. the
    # shutil.copy2 we just did for backup) can hold a transient lock on
    # ``target`` and make ``os.replace`` raise WinError 5. Retry briefly
    # with backoff before giving up.
    last_exc: Optional[OSError] = None
    for delay in (0.0, 0.02, 0.05, 0.1, 0.2):
        if delay:
            time.sleep(delay)
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:
            last_exc = exc
    assert last_exc is not None
    raise last_exc


def _atomic_write(target: Path, doc: Any, yaml: YAML) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            yaml.dump(doc, fh)
        _atomic_replace(tmp, target)
    except Exception:
        # Best-effort cleanup of the temp file so a failed save
        # doesn't leave clutter next to config.yaml.
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def save_patch(
    patch: dict[str, Any],
    *,
    target: Optional[Path] = None,
) -> dict[str, Any]:
    """Apply ``patch`` to the on-disk config and return an audit dict.

    Behaviour:

    - Loads the existing YAML with ruamel (preserving comments).
    - Falls back to an empty :class:`CommentedMap` when no file
      exists, so a fresh deployment can be configured from the GUI.
    - Applies the patch in place.
    - Backs up + atomically writes.

    The returned dict is intentionally small: it is JSON-serialisable
    and is what the API endpoint echoes to the caller. The caller is
    responsible for redacting secrets before logging or returning it
    to the client.
    """
    target_path = (target or resolve_write_path()).resolve()
    yaml = _make_yaml()

    with _WRITE_LOCK:
        if target_path.exists():
            with target_path.open("r", encoding="utf-8") as fh:
                doc = yaml.load(fh)
            if doc is None:
                doc = CommentedMap()
            elif not isinstance(doc, dict):
                raise ValueError(
                    f"{target_path} root is not a mapping; refusing to write"
                )
        else:
            doc = CommentedMap()

        _apply_patch_in_place(doc, patch)

        backup_path = _backup_existing(target_path)
        _atomic_write(target_path, doc, yaml)

    return {
        "target_path": str(target_path),
        "backup_path": str(backup_path) if backup_path else None,
    }
