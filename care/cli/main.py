"""care CLI.

Pure stdlib (argparse). Subcommands:

    process                 — run the pipeline against a directory
    inspect                 — show file inspection summary
    list-plugins            — list registered providers
    verify-offline          — confirm offline guard + HF env
    validate-template       — load and validate a template YAML
    serve                   — bind FastAPI to 127.0.0.1 (uvicorn required)
    app                     — desktop wrapper: serve + pywebview window
    compute-model-checksums — emit per-file SHA-256 of a local model dir
    generate-sbom           — emit the care SBOM (packages + model manifest + licenses)
    scan-frontend-assets    — scan frontend/ for external URLs

Every command runs offline-by-default and never modifies inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from ..core.config import AppConfig, load_config
from ..core.constants import APP_NAME, APP_VERSION, DEFAULT_HOST, DEFAULT_PORT, HF_OFFLINE_ENV


def _load_config(path: str | None) -> AppConfig:
    return load_config(path) if path else load_config()


# ----- process ---------------------------------------------------------------


def cmd_process(args: argparse.Namespace) -> int:
    from ..templates import load_templates_from_directory
    from ..templates.registry import TemplateRegistry
    from ..workers.pipeline import run_pipeline

    cfg = _load_config(args.config)
    if args.work_dir:
        cfg.paths.work_dir = args.work_dir
    if args.export_dir:
        cfg.paths.export_dir = args.export_dir
    if args.templates_dir:
        cfg.paths.templates_dir = args.templates_dir

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"error: input_dir {input_dir} not found or not a directory", file=sys.stderr)
        return 2

    template_registry = None
    template_ids = (
        [tid.strip() for tid in args.template_ids.split(",") if tid.strip()]
        if args.template_ids
        else None
    )
    if args.jurisdiction or template_ids:
        template_registry = TemplateRegistry(
            load_templates_from_directory(cfg.paths.templates_dir)
        ).filter_by(jurisdiction=args.jurisdiction, template_ids=template_ids)

    result = run_pipeline(input_dir, config=cfg, template_registry=template_registry)
    summary = {
        "input_dir": str(input_dir),
        "files_processed": len(result.file_entries),
        "reports": [
            {
                "report_id": a.file_entry.sha256[:16],
                "source_file_name": a.file_entry.name,
                "template_id": a.template_match.template_id,
                "template_confidence": round(a.template_match.confidence, 4),
                "qa_decision": a.qa.export_decision,
                "qa_export_blocked": a.qa.export_blocked,
                "blocking_reasons": list(a.qa.blocking_reasons),
                "export_dir": (
                    a.export_result.output_dir
                    if a.export_result and not a.export_result.skipped
                    else None
                ),
            }
            for a in result.artifacts
        ],
    }
    print(json.dumps(summary, indent=2))
    blocked = sum(1 for a in result.artifacts if a.qa.export_blocked)
    return 1 if blocked and args.fail_on_block else 0


# ----- inspect ---------------------------------------------------------------


def cmd_inspect(args: argparse.Namespace) -> int:
    from ..pdf.pypdfium2_backend import PypdfiumPDFImageBackend

    target = Path(args.path).resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    backend = PypdfiumPDFImageBackend()
    inspection = backend.inspect_file(target)
    print(json.dumps(
        {
            "path": str(target),
            "file_type": inspection.file_type,
            "page_count": inspection.page_count,
            "page_dimensions": list(inspection.page_dimensions),
            "has_text_layer": inspection.has_text_layer,
            "appears_image_only": inspection.appears_image_only,
            "requires_ocr": inspection.requires_ocr,
            "page_has_text": list(inspection.page_has_text),
            "rotation": list(inspection.rotation),
            "warnings": list(inspection.warnings),
        },
        indent=2,
    ))
    return 0


# ----- list-plugins ----------------------------------------------------------


def cmd_list_plugins(args: argparse.Namespace) -> int:
    from ..document_ai.registry import get_registry as get_vlm_registry
    from ..ocr.registry import get_registry as get_ocr_registry
    from ..pii.registry import get_registry as get_pii_registry

    def _summary(reg):
        return [
            {
                "name": n,
                "version": getattr(reg.get(n), "version", "unknown"),
                "provider_type": getattr(reg.get(n), "provider_type", "unknown"),
                "enabled_by_default": bool(
                    getattr(reg.get(n), "enabled_by_default", False)
                ),
                "requires_network": bool(
                    getattr(reg.get(n), "requires_network", False)
                ),
            }
            for n in reg.names()
        ]

    payload = {
        "ocr": _summary(get_ocr_registry()),
        "document_ai": _summary(get_vlm_registry()),
        "pii": _summary(get_pii_registry()),
    }
    print(json.dumps(payload, indent=2))
    return 0


# ----- verify-offline --------------------------------------------------------


def cmd_verify_offline(args: argparse.Namespace) -> int:
    from ..core.offline_guard import enable, is_enabled

    cfg = _load_config(args.config)
    if not is_enabled():
        enable()
    issues: list[str] = []
    for key, expected in HF_OFFLINE_ENV.items():
        actual = os.environ.get(key)
        if actual != expected:
            issues.append(f"{key} must be {expected!r}, got {actual!r}")
    if not cfg.offline.enabled:
        issues.append("offline.enabled is False in config")
    if not cfg.offline.block_network:
        issues.append("offline.block_network is False in config")
    if not is_enabled():
        issues.append("offline guard could not be enabled")
    payload = {
        "offline_guard_enabled": is_enabled(),
        "offline_config_enabled": bool(cfg.offline.enabled),
        "block_network": bool(cfg.offline.block_network),
        "hf_env_ok": not any(issue.startswith(("HF_", "TRANSFORMERS_")) for issue in issues),
        "issues": issues,
    }
    print(json.dumps(payload, indent=2))
    return 0 if not issues else 1


# ----- validate-template -----------------------------------------------------


def cmd_validate_template(args: argparse.Namespace) -> int:
    from ..templates.loader import load_template_yaml

    target = Path(args.path).resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    try:
        template = load_template_yaml(target)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(
        {
            "valid": True,
            "template_id": template.template_id,
            "version": template.version,
            "anchor_count": len(template.signature.anchor_text),
            "regions": sorted(template.regions.keys()),
            "form_number_regex": template.signature.form_number_regex,
        },
        indent=2,
    ))
    return 0


# ----- serve -----------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    from ..core.runtime_state import set_boot_snapshot

    cfg = _load_config(args.config)
    host = args.host or cfg.server.host or DEFAULT_HOST
    port = int(args.port or cfg.server.port or DEFAULT_PORT)
    if host not in {"127.0.0.1", "localhost", "::1"} and not args.allow_non_loopback:
        print(
            f"refusing to bind to non-loopback host {host!r}; pass "
            "--allow-non-loopback to override",
            file=sys.stderr,
        )
        return 2
    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError:
        print(
            "uvicorn is not installed in this environment. "
            "Install via offline wheelhouse and retry. "
            "(See docs/packaging.md.)",
            file=sys.stderr,
        )
        return 3
    # Phase 13.7 — capture the values uvicorn is about to bind with so
    # the GUI can spot drift (e.g., the operator changed server.port
    # via Settings; we should warn that a restart is required).
    set_boot_snapshot(
        host=host,
        port=port,
        expose_to_network=bool(cfg.server.expose_to_network),
    )
    uvicorn.run(  # pragma: no cover - exec'd only on real serve
        "care.main:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )
    return 0


# ----- app -------------------------------------------------------------------


def cmd_app(args: argparse.Namespace) -> int:
    """Open the desktop window pointing at our FastAPI server.

    Spawns ``cli serve`` as a subprocess, polls /api/health, then
    opens a pywebview window. On window close, terminates the
    subprocess. The host is locked to loopback — there's no
    ``--allow-non-loopback`` escape hatch on this command.
    """
    from .desktop import (
        DEFAULT_HEIGHT,
        DEFAULT_TITLE,
        DEFAULT_WIDTH,
        run_app,
    )

    cfg = _load_config(args.config)
    config_path = Path(args.config).resolve() if args.config else None
    return run_app(
        config=cfg,
        config_path=config_path,
        host=args.host or DEFAULT_HOST,
        port=int(args.port or cfg.server.port or DEFAULT_PORT),
        title=args.title or DEFAULT_TITLE,
        width=int(args.width or DEFAULT_WIDTH),
        height=int(args.height or DEFAULT_HEIGHT),
    )


# ----- install-shortcut / uninstall-shortcut -------------------------------


def cmd_install_shortcut(args: argparse.Namespace) -> int:
    from .shortcut import install_shortcut

    config_path = Path(args.config).resolve() if args.config else None
    icon_path = Path(args.icon).resolve() if args.icon else None
    install_root = Path(args.install_root).resolve() if args.install_root else None
    try:
        result = install_shortcut(
            config_path=config_path,
            install_root=install_root,
            icon_path=icon_path,
        )
    except (RuntimeError, OSError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if isinstance(result, tuple):
        # Linux returns (applications_path, desktop_path)
        for p in result:
            print(f"created: {p}")
    else:
        print(f"created: {result}")
    return 0


def cmd_uninstall_shortcut(args: argparse.Namespace) -> int:
    from .shortcut import uninstall_shortcut

    try:
        removed = uninstall_shortcut()
    except (RuntimeError, OSError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print("removed" if removed else "no shortcut found")
    return 0


# ----- compute-model-checksums ----------------------------------------------


def cmd_compute_model_checksums(args: argparse.Namespace) -> int:
    target = Path(args.model_dir).resolve()
    if not target.exists() or not target.is_dir():
        print(f"error: {target} does not exist or is not a directory", file=sys.stderr)
        return 2
    checksums: dict[str, str] = {}
    for f in sorted(target.rglob("*")):
        if not f.is_file():
            continue
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        checksums[str(f.relative_to(target))] = h.hexdigest()
    print(json.dumps(
        {"model_dir": str(target), "checksums": checksums},
        indent=2,
    ))
    return 0


# ----- generate-sbom ---------------------------------------------------------


def cmd_generate_sbom(args: argparse.Namespace) -> int:
    """Emit the care SBOM document.

    Combines a Python package list, a per-provider model manifest, and a
    flat license report into one ``care.sbom.v1`` JSON
    document. Air-gapped operators can use this to audit what would
    load, what licenses are at play, and which model files were
    delivered alongside the binary.
    """
    from ..audit import build_sbom

    cfg = _load_config(args.config) if args.config else None
    models_dir = Path(args.models_dir) if args.models_dir else (
        Path(cfg.paths.models_dir) if cfg else Path("models")
    )
    payload = build_sbom(
        models_dir=models_dir,
        include_packages=not args.no_packages,
    )
    out = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(out)
    return 0


def cmd_model_manifest(args: argparse.Namespace) -> int:
    """Emit only the model-manifest section of the SBOM."""
    from ..audit import build_model_manifest

    cfg = _load_config(args.config) if args.config else None
    models_dir = Path(args.models_dir) if args.models_dir else (
        Path(cfg.paths.models_dir) if cfg else Path("models")
    )
    payload = build_model_manifest(models_dir=models_dir)
    out = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        print(out)
    return 0


# ----- scan-frontend-assets --------------------------------------------------


EXTERNAL_URL_RE = re.compile(
    r"""(?i)(https?://(?!127\.0\.0\.1|localhost)|//(?!127\.0\.0\.1|localhost))"""
)


def cmd_scan_frontend_assets(args: argparse.Namespace) -> int:
    target = Path(args.frontend_dir).resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    findings: list[dict[str, object]] = []
    for path in target.rglob("*"):
        if path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in EXTERNAL_URL_RE.finditer(text):
            findings.append(
                {
                    "file": str(path.relative_to(target)),
                    "match": m.group(0),
                    "offset": m.start(),
                }
            )
    payload = {
        "frontend_dir": str(target),
        "files_scanned": sum(
            1
            for p in target.rglob("*")
            if p.suffix.lower() in {".html", ".css", ".js"}
        ),
        "external_url_count": len(findings),
        "findings": findings,
    }
    print(json.dumps(payload, indent=2))
    return 1 if findings else 0


# ----- llm-test --------------------------------------------------------------


def cmd_llm_test(args: argparse.Namespace) -> int:
    """Round-trip a single prompt against a configured LLM provider.

    Lets operators verify a real API key / endpoint without running
    the whole pipeline. Output is JSON; everything except the
    response text is metadata an audit log can keep. The redactor
    keeps API keys out of any output even if the operator asks for
    --show-config.
    """
    import os

    from ..llm import get_registry as get_llm_registry
    from ..llm.safety import redact_secrets

    cfg = _load_config(args.config)
    provider_cfg: dict[str, object] = dict(
        cfg.llm.providers.get(args.provider, {}) or {}
    )
    provider_cfg["_app_config"] = {"offline_enabled": cfg.offline.enabled}

    if args.api_key_env:
        env_value = os.environ.get(args.api_key_env)
        if env_value:
            provider_cfg["api_key"] = env_value
    if args.api_key:
        provider_cfg["api_key"] = args.api_key
    if args.acknowledge_egress:
        provider_cfg["acknowledged_external_data_egress"] = True
    if args.model:
        provider_cfg["model"] = args.model
    if args.endpoint_url:
        provider_cfg["endpoint_url"] = args.endpoint_url

    try:
        cls = get_llm_registry().get(args.provider)
    except Exception as exc:  # noqa: BLE001
        print(f"error: unknown provider {args.provider!r}: {exc}", file=sys.stderr)
        return 2

    provider = cls()
    try:
        provider.load(provider_cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"error: load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    try:
        if args.image:
            result = provider.analyze_image(args.image, args.prompt)
        else:
            result = provider.generate_text(args.prompt)
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: inference failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "provider": result.provider,
        "model": result.model,
        "finish_reason": result.finish_reason,
        "usage": result.usage,
        "warnings": result.warnings,
        "requires_review": result.requires_review,
        "text": result.text,
    }
    if args.show_config:
        payload["config"] = redact_secrets(provider_cfg)
    print(json.dumps(payload, indent=2))
    return 0


# ----- pii-test --------------------------------------------------------------


def cmd_pii_test(args: argparse.Namespace) -> int:
    """Round-trip a single text snippet through a configured PII provider.

    Lets operators verify a real model dir (e.g., Piiranha) detects
    the entities they expect on a known sample, without running the
    whole pipeline. Output is JSON. The text input is read from the
    command line; we never log it under any logging level.
    """
    from ..pii.registry import get_registry as get_pii_registry

    cfg = _load_config(args.config)
    provider_cfg: dict[str, object] = dict(
        cfg.pii.providers.get(args.provider, {}) or {}
    )

    if args.model_dir:
        provider_cfg["model_dir"] = args.model_dir
    if args.min_confidence is not None:
        provider_cfg["min_confidence"] = args.min_confidence
    if args.aggregation_strategy:
        provider_cfg["aggregation_strategy"] = args.aggregation_strategy

    if args.text_file:
        text_path = Path(args.text_file)
        if not text_path.exists():
            print(
                f"error: text-file {text_path} does not exist", file=sys.stderr
            )
            return 2
        text = text_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = args.text or ""
    if not text:
        print("error: pass --text or --text-file", file=sys.stderr)
        return 2

    try:
        cls = get_pii_registry().get(args.provider)
    except Exception as exc:  # noqa: BLE001
        print(f"error: unknown PII provider {args.provider!r}: {exc}", file=sys.stderr)
        return 2

    provider = cls()
    try:
        provider.load(provider_cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"error: load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    try:
        entities = provider.detect_text(text)
    except Exception as exc:  # noqa: BLE001
        print(f"error: inference failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    payload: dict[str, object] = {
        "provider": args.provider,
        "input_length": len(text),
        "entity_count": len(entities),
        "entities": [
            {
                "entity_type": e.entity_type,
                "text_preview": (e.text[:64] + ("…" if len(e.text) > 64 else ""))
                if not args.show_text
                else e.text,
                "start_offset": e.start_offset,
                "end_offset": e.end_offset,
                "confidence": round(e.confidence, 4),
                "provider": e.provider,
                "detection_reason": e.detection_reason,
                "requires_review": e.requires_review,
            }
            for e in entities
        ],
    }
    if args.show_manifest:
        payload["manifest"] = provider.get_model_manifest()
    if args.show_raw:
        # Surface the raw pre-mapping pipeline output if the provider
        # exposes it. Useful for diagnosing "why didn't this entity
        # come through?" — the operator can see what the model
        # actually returned vs what we filtered/mapped to.
        raw = getattr(provider, "_last_raw_spans", None)
        if raw is not None:
            payload["raw_spans"] = raw
    print(json.dumps(payload, indent=2))
    return 0


# ----- argparse wiring -------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="care",
        description=f"{APP_NAME} {APP_VERSION} — offline crash report extractor",
    )
    parser.add_argument("--version", action="version", version=APP_VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="run the pipeline on a directory")
    p.add_argument("input_dir")
    p.add_argument("--config", default=None)
    p.add_argument("--work-dir", default=None)
    p.add_argument("--export-dir", default=None)
    p.add_argument("--templates-dir", default=None)
    p.add_argument(
        "--jurisdiction",
        default=None,
        help="restrict template matching to this jurisdiction (per-job allowlist)",
    )
    p.add_argument(
        "--template-ids",
        default=None,
        help=(
            "comma-separated template_id allowlist. Empty/missing means use "
            "every template under --templates-dir."
        ),
    )
    p.add_argument(
        "--fail-on-block",
        action="store_true",
        help="exit non-zero if any report is blocked by the QA gate",
    )
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("inspect", help="show inspection summary for one file")
    p.add_argument("path")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("list-plugins", help="list registered providers")
    p.set_defaults(func=cmd_list_plugins)

    p = sub.add_parser("verify-offline", help="verify offline mode + HF env vars")
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_verify_offline)

    p = sub.add_parser("validate-template", help="validate a template YAML")
    p.add_argument("path")
    p.set_defaults(func=cmd_validate_template)

    p = sub.add_parser("serve", help="bind FastAPI to 127.0.0.1 (uvicorn required)")
    p.add_argument("--config", default=None)
    p.add_argument("--host", default=None)
    p.add_argument("--port", default=None, type=int)
    p.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="allow binding to a non-loopback host (DISCOURAGED)",
    )
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser(
        "app",
        help="desktop wrapper: spawn the server and open a pywebview window",
    )
    p.add_argument("--config", default=None)
    p.add_argument(
        "--host",
        default=None,
        help="loopback host (127.0.0.1 / localhost / ::1). Non-loopback "
        "hosts are rejected; this command has no override.",
    )
    p.add_argument("--port", default=None, type=int)
    p.add_argument("--title", default=None, help="window title")
    p.add_argument("--width", default=None, type=int)
    p.add_argument("--height", default=None, type=int)
    p.set_defaults(func=cmd_app)

    p = sub.add_parser(
        "install-shortcut",
        help="create a desktop launcher icon for the app subcommand",
    )
    p.add_argument(
        "--config",
        default=None,
        help="absolute path to config.yaml the launcher should pass to `app`",
    )
    p.add_argument(
        "--icon",
        default=None,
        help="optional path to an icon file (.ico/.icns/.png per platform)",
    )
    p.add_argument(
        "--install-root",
        default=None,
        help="working directory the launcher should set as cwd "
        "(defaults to the repo root)",
    )
    p.set_defaults(func=cmd_install_shortcut)

    p = sub.add_parser(
        "uninstall-shortcut",
        help="remove the desktop launcher icon (if present)",
    )
    p.set_defaults(func=cmd_uninstall_shortcut)

    p = sub.add_parser(
        "compute-model-checksums", help="SHA-256 every file under a model dir"
    )
    p.add_argument("model_dir")
    p.set_defaults(func=cmd_compute_model_checksums)

    p = sub.add_parser(
        "generate-sbom",
        help="emit the care SBOM (deps + model manifest + licenses)",
    )
    p.add_argument("--output", default=None)
    p.add_argument("--config", default=None)
    p.add_argument(
        "--models-dir",
        default=None,
        help="path to models/ (default: from config or ./models)",
    )
    p.add_argument(
        "--no-packages",
        action="store_true",
        help="omit the Python dependency list (model manifest + licenses only)",
    )
    p.set_defaults(func=cmd_generate_sbom)

    p = sub.add_parser(
        "model-manifest",
        help="emit only the per-provider model manifest section",
    )
    p.add_argument("--output", default=None)
    p.add_argument("--config", default=None)
    p.add_argument("--models-dir", default=None)
    p.set_defaults(func=cmd_model_manifest)

    p = sub.add_parser(
        "scan-frontend-assets", help="scan frontend/ for non-local URLs"
    )
    p.add_argument("frontend_dir")
    p.set_defaults(func=cmd_scan_frontend_assets)

    p = sub.add_parser(
        "llm-test",
        help="round-trip a single prompt through a configured LLM provider",
    )
    p.add_argument(
        "provider",
        help="registered name (openai, gemini, anthropic, ollama, vllm, "
        "llamacpp, hf_local, mock_llm)",
    )
    p.add_argument(
        "--prompt",
        default="Reply with the single word OK.",
        help="prompt to send",
    )
    p.add_argument(
        "--image",
        default=None,
        help="optional path to an image file for vision-capable providers",
    )
    p.add_argument(
        "--api-key",
        default=None,
        help="override api_key (cloud providers). Prefer --api-key-env.",
    )
    p.add_argument(
        "--api-key-env",
        default=None,
        help="env var to read the api_key from (e.g. OPENAI_API_KEY)",
    )
    p.add_argument(
        "--acknowledge-egress",
        action="store_true",
        help="set acknowledged_external_data_egress=true for this run "
        "(cloud providers only)",
    )
    p.add_argument("--model", default=None, help="override model name")
    p.add_argument(
        "--endpoint-url",
        default=None,
        help="override endpoint URL (local-server providers only)",
    )
    p.add_argument(
        "--show-config",
        action="store_true",
        help="include the redacted provider config in the output",
    )
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_llm_test)

    p = sub.add_parser(
        "pii-test",
        help="round-trip a single text snippet through a configured PII provider",
    )
    p.add_argument(
        "provider",
        help="registered name (regex, presidio, piiranha, mock_pii)",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--text", default=None, help="raw text to analyse")
    g.add_argument(
        "--text-file", default=None, help="path to a UTF-8 text file"
    )
    p.add_argument(
        "--model-dir",
        default=None,
        help="override model_dir (HF-based providers like piiranha/presidio)",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=None,
        help="override the provider's min_confidence threshold",
    )
    p.add_argument(
        "--show-text",
        action="store_true",
        help="print full matched text in the output (default truncates to 64 chars)",
    )
    p.add_argument(
        "--show-manifest",
        action="store_true",
        help="include the provider's model manifest in the output",
    )
    p.add_argument(
        "--show-raw",
        action="store_true",
        help="also print the raw pre-mapping pipeline output (HF NER spans)",
    )
    p.add_argument(
        "--aggregation-strategy",
        default=None,
        choices=["none", "simple", "first", "average", "max"],
        help="override the HF token-classification aggregation strategy",
    )
    p.add_argument("--config", default=None)
    p.set_defaults(func=cmd_pii_test)

    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":  # pragma: no cover
    main()
