"""YAML template loader.

Phase 9 adds template inheritance via the optional ``extends`` field:
a child template's YAML is dict-merged on top of the parent's
(parent → child) before the result is validated against
:class:`TemplateSchema`. The merge is intentionally simple and
predictable:

- Top-level scalars (``version``, ``jurisdiction``, ``agency``, …):
  child wins if set.
- ``signature.anchor_text``: child wins **wholesale** if present
  (no list merging — operators wanting append should re-list).
- ``signature.form_number_regex``: child wins if set.
- ``layout``: child wins per-key.
- ``regions``: per-region-key merge (child's ``narrative`` block
  overrides parent's ``narrative`` block at the field level; regions
  the child doesn't mention are inherited as-is).

Cycles and missing parents both raise :class:`ConfigError` — they're
operator typos, not runtime data, so failing closed at load time is
the right call.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ..core.errors import ConfigError
from .schemas import TemplateSchema

_INHERITANCE_KEYS = ("signature", "layout", "regions")


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read template {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in template {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Template root must be a mapping in {path}")
    return data


def load_template_yaml(path: Path | str) -> TemplateSchema:
    p = Path(path)
    data = _read_yaml(p)
    if data.get("extends"):
        # Single-file load can't honor inheritance — the parent has to
        # be resolvable from somewhere. Strip ``extends`` and warn the
        # caller via ConfigError so they switch to the directory-based
        # loader. (We don't silently drop it; that hides bugs.)
        raise ConfigError(
            f"Template {p} declares extends={data['extends']!r}; "
            "inheritance only resolves through load_templates_from_directory()."
        )
    try:
        return TemplateSchema.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid template {p}: {exc}") from exc


def _merge_template_dicts(parent: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    """Merge ``child`` over ``parent`` per the inheritance rules above.

    Returns a fresh dict; neither input is mutated.
    """
    merged: dict[str, Any] = dict(parent)
    for key, value in child.items():
        if key == "regions" and isinstance(value, dict) and isinstance(parent.get("regions"), dict):
            # Per-region-key field-level merge.
            base_regions: dict[str, Any] = dict(parent["regions"])
            for region_key, region_val in value.items():
                if isinstance(region_val, dict) and isinstance(base_regions.get(region_key), dict):
                    base_regions[region_key] = {**base_regions[region_key], **region_val}
                else:
                    base_regions[region_key] = region_val
            merged["regions"] = base_regions
        elif key in _INHERITANCE_KEYS and isinstance(value, dict) and isinstance(parent.get(key), dict):
            # Field-level merge for signature/layout. Child keys win.
            merged[key] = {**parent[key], **value}
        else:
            merged[key] = value
    # ``extends`` itself shouldn't propagate through the resolved doc.
    merged.pop("extends", None)
    return merged


def _resolve_inheritance(
    raw_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve every template's parent chain to a flat dict.

    Detects cycles and missing parents and raises ConfigError with a
    message naming the offender so operators can locate their typo
    fast.
    """
    resolved: dict[str, dict[str, Any]] = {}

    def resolve(template_id: str, chain: tuple[str, ...]) -> dict[str, Any]:
        if template_id in resolved:
            return resolved[template_id]
        if template_id in chain:
            cycle = " -> ".join([*chain, template_id])
            raise ConfigError(f"Template inheritance cycle: {cycle}")
        if template_id not in raw_by_id:
            raise ConfigError(
                f"Template {chain[-1]!r} extends unknown parent {template_id!r}"
            )
        node = raw_by_id[template_id]
        parent_id = node.get("extends")
        if not parent_id:
            resolved[template_id] = dict(node)
            resolved[template_id].pop("extends", None)
            return resolved[template_id]
        parent_resolved = resolve(parent_id, chain + (template_id,))
        merged = _merge_template_dicts(parent_resolved, node)
        # Child must keep its own template_id even though the merge
        # would otherwise inherit it from the parent (parent's id was
        # also overwritten by the child's, but be explicit).
        merged["template_id"] = template_id
        resolved[template_id] = merged
        return merged

    for template_id in raw_by_id:
        resolve(template_id, ())
    return resolved


def load_templates_from_directory(directory: Path | str) -> list[TemplateSchema]:
    """Recursively load every *.yaml / *.yml file under `directory`.

    Templates may declare ``extends: <other_template_id>``; inheritance
    is resolved across every YAML file in this directory tree before
    final validation. Returns an empty list if the directory does not
    exist.
    """
    d = Path(directory)
    if not d.exists():
        return []
    if not d.is_dir():
        raise NotADirectoryError(d)
    files: list[Path] = sorted(set(d.rglob("*.yaml")) | set(d.rglob("*.yml")))

    raw_by_id: dict[str, dict[str, Any]] = {}
    paths_by_id: dict[str, Path] = {}
    for file_path in files:
        data = _read_yaml(file_path)
        template_id = data.get("template_id")
        if not isinstance(template_id, str) or not template_id:
            raise ConfigError(
                f"Template {file_path} is missing a string template_id"
            )
        if template_id in raw_by_id:
            raise ConfigError(
                f"Duplicate template_id {template_id!r} in "
                f"{paths_by_id[template_id]} and {file_path}"
            )
        raw_by_id[template_id] = data
        paths_by_id[template_id] = file_path

    resolved = _resolve_inheritance(raw_by_id)

    templates: list[TemplateSchema] = []
    for template_id, data in resolved.items():
        try:
            templates.append(TemplateSchema.model_validate(data))
        except ValidationError as exc:
            raise ConfigError(
                f"Invalid template {paths_by_id[template_id]} "
                f"(after inheritance resolution): {exc}"
            ) from exc
    templates.sort(key=lambda t: t.template_id)
    return templates
