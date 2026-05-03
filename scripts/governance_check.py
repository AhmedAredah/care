#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Make care.core.governance_guard importable when this script is
# run directly (``python scripts/governance_check.py``) without uv.
sys.path.insert(0, str(ROOT))

FAILURES: list[str] = []


def fail(message: str) -> None:
    FAILURES.append(message)


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        fail(f"Missing required file: {path.relative_to(ROOT)}")
        return ""


def require_file(rel: str) -> None:
    path = ROOT / rel
    if not path.exists():
        fail(f"Missing required file: {rel}")


def check_required_files() -> None:
    required = [
        "GOVERNANCE.md",
        "care/ocr/base.py",
        "care/ocr/registry.py",
        "care/document_ai/base.py",
        "care/document_ai/registry.py",
        "care/pii/base.py",
        "care/pii/registry.py",
        "care/document_ir/models.py",
        "care/workers/pipeline.py",
        "docs/offline-mode.md",
        "docs/plugin-system.md",
        "docs/document-ai-plugins.md",
        "docs/pii-policy.md",
    ]
    for rel in required:
        require_file(rel)


def check_frontend_no_external_assets() -> None:
    frontend = ROOT / "frontend"
    if not frontend.exists():
        return

    external_url = re.compile(
        r"""(?i)(https?://(?!127\.0\.0\.1|localhost)|//(?!127\.0\.0\.1|localhost))"""
    )

    for path in frontend.rglob("*"):
        if path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        text = read(path)
        if external_url.search(text):
            fail(f"External URL found in frontend asset: {path.relative_to(ROOT)}")


def check_default_config_safety() -> None:
    candidates = [
        ROOT / "config.yaml",
        ROOT / "config.yml",
        ROOT / "backend" / "config.yaml",
        ROOT / "backend" / "config.yml",
    ]

    existing = [p for p in candidates if p.exists()]
    if not existing:
        return

    combined = "\n".join(read(p) for p in existing).lower()

    unsafe_expectations = [
        ("piiranha", "enabled: true", "Piiranha must not be enabled by default."),
        ("kosmos25", "enabled: true", "Kosmos-2.5 must not be enabled by default."),
        ("document_ai", "enabled: true", "Document-AI/VLM must not be globally enabled by default."),
    ]

    for section, bad_value, message in unsafe_expectations:
        idx = combined.find(section)
        if idx != -1:
            window = combined[idx : idx + 400]
            if bad_value in window:
                fail(message)

    forbidden_defaults = [
        "azure",
        "textract",
        "google document ai",
        "google_document_ai",
        "cloud_ocr",
    ]

    for item in forbidden_defaults:
        if f"provider: {item}" in combined or f"- {item}" in combined:
            fail(f"Cloud/network provider appears in default provider chain: {item}")


def check_no_public_export_of_originals() -> None:
    export_files = list((ROOT / "backend" / "app" / "export").rglob("*.py"))
    for path in export_files:
        text = read(path).lower()
        suspicious = [
            "include_original_pdf = true",
            '"include_original_pdf": true',
            "include_unredacted_text = true",
            '"include_unredacted_text": true',
        ]
        for marker in suspicious:
            if marker in text:
                fail(f"Unsafe public export marker found in {path.relative_to(ROOT)}: {marker}")


def check_desktop_module_no_external_urls() -> None:
    """The pywebview wrapper must only ever load loopback URLs.

    Phase 14.4 — defensive substring scan over care/cli/desktop.py
    and care/cli/shortcut.py: any ``http://`` / ``https://`` host
    other than ``127.0.0.1`` / ``localhost`` is a bug.
    """
    suspect = re.compile(
        r"https?://(?!127\.0\.0\.1|localhost)[A-Za-z0-9.\-]+",
        re.IGNORECASE,
    )
    targets = [
        ROOT / "backend" / "app" / "cli" / "desktop.py",
        ROOT / "backend" / "app" / "cli" / "shortcut.py",
    ]
    for path in targets:
        if not path.exists():
            continue
        text = read(path)
        for match in suspect.finditer(text):
            fail(
                f"Non-loopback URL in {path.relative_to(ROOT)}: "
                f"{match.group(0)!r}"
            )


def check_plugin_manifests_disable_unsafe_defaults() -> None:
    """Forward guard for per-plugin installer manifests (Phase 2+).

    Per-plugin installers ship a ``plugin.toml`` at the bundle root.
    The contract requires that no installer enable Piiranha,
    Kosmos-2.5, or any document_ai provider by default — operators
    must opt in explicitly after a license review. This check is a
    no-op until plugin.toml files appear in the tree.
    """
    try:
        import tomllib
    except ImportError as exc:  # pragma: no cover — Python <3.11
        fail(f"governance_check could not import tomllib: {exc}")
        return

    unsafe_providers = {"piiranha", "kosmos25"}
    for manifest in ROOT.rglob("plugin.toml"):
        # Skip vendored/test fixtures so they don't poison the gate.
        if any(part in {".venv", ".venv-test", "node_modules"} for part in manifest.parts):
            continue
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            fail(f"{manifest.relative_to(ROOT)} is not valid TOML: {exc}")
            continue

        plugin_section = data.get("plugin", {})
        providers = plugin_section.get("providers") or []
        if not isinstance(providers, list):
            providers = []

        defaults = data.get("defaults", {}) or {}
        for provider_name in providers:
            if provider_name in unsafe_providers and defaults.get(provider_name, {}).get("enabled") is True:
                fail(
                    f"{manifest.relative_to(ROOT)}: provider {provider_name!r} "
                    "must not be enabled by default in a plugin manifest "
                    "(license-review-required)."
                )
            if defaults.get(provider_name, {}).get("category") == "document_ai" and defaults[provider_name].get("enabled") is True:
                fail(
                    f"{manifest.relative_to(ROOT)}: document_ai provider "
                    f"{provider_name!r} must not be enabled by default."
                )


def check_locked_keys() -> None:
    """Re-use the runtime guard table to enforce that no config.yaml
    on disk has flipped a locked key.

    The runtime table at ``care/core/governance_guard.py`` is the
    single source of truth. This check parses every candidate config
    file as YAML and asks the same code that the API uses.
    """
    try:
        import yaml  # type: ignore[import-not-found]

        from care.core.governance_guard import check_immutable_violations
    except ImportError as exc:
        fail(f"governance_check could not import governance_guard / yaml: {exc}")
        return

    candidates = [
        ROOT / "config.yaml",
        ROOT / "config.yml",
        ROOT / "backend" / "config.yaml",
        ROOT / "backend" / "config.yml",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(read(path)) or {}
        except yaml.YAMLError as exc:
            fail(f"{path.relative_to(ROOT)} is not valid YAML: {exc}")
            continue
        if not isinstance(data, dict):
            fail(f"{path.relative_to(ROOT)} root is not a mapping")
            continue
        for violation in check_immutable_violations(data):
            fail(
                f"{path.relative_to(ROOT)}: {violation}"
            )


def main() -> int:
    check_required_files()
    check_frontend_no_external_assets()
    check_default_config_safety()
    check_locked_keys()
    check_no_public_export_of_originals()
    check_desktop_module_no_external_urls()
    check_plugin_manifests_disable_unsafe_defaults()

    if FAILURES:
        print("\nPolicy check FAILED\n")
        for item in FAILURES:
            print(f"- {item}")
        return 1

    print("Policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
