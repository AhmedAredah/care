"""Frontend asset locality tests."""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

EXTERNAL_URL_RE = re.compile(
    r"""(?i)(https?://(?!127\.0\.0\.1|localhost)|//(?!127\.0\.0\.1|localhost))"""
)


def _frontend_files(exts: set[str]) -> list[Path]:
    if not FRONTEND_DIR.exists():
        return []
    return [p for p in FRONTEND_DIR.rglob("*") if p.suffix.lower() in exts]


def test_frontend_directory_exists() -> None:
    assert FRONTEND_DIR.exists()
    assert (FRONTEND_DIR / "index.html").exists()


def test_frontend_contains_no_external_urls() -> None:
    findings: list[tuple[str, str]] = []
    for path in _frontend_files({".html", ".css", ".js"}):
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in EXTERNAL_URL_RE.finditer(text):
            findings.append((str(path.relative_to(FRONTEND_DIR)), m.group(0)))
    assert findings == [], f"external URLs found: {findings}"


def test_frontend_html_does_not_link_remote_fonts_or_styles() -> None:
    """Per-tag check: no <script src="http..."> or <link href="http...">."""
    bad_patterns = [
        re.compile(r"""(?i)<\s*script[^>]*\bsrc\s*=\s*["']https?://"""),
        re.compile(r"""(?i)<\s*link[^>]*\bhref\s*=\s*["']https?://"""),
        re.compile(r"""(?i)<\s*img[^>]*\bsrc\s*=\s*["']https?://"""),
        re.compile(r"""(?i)@import\s+url\(['"]?https?://"""),
        re.compile(r"""(?i)url\(['"]?https?://"""),
    ]
    for path in _frontend_files({".html", ".css"}):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in bad_patterns:
            assert not pattern.search(text), (
                f"forbidden remote reference in {path.name}: {pattern.pattern}"
            )


def test_frontend_js_only_targets_local_api() -> None:
    """Every fetch() call must target a path starting with '/api' or '/'.
    No fetch to a different origin is allowed."""
    js_files = _frontend_files({".js"})
    fetch_call_re = re.compile(r"""fetch\s*\(\s*([A-Za-z_$][\w$]*\s*\+\s*)?["']([^"']+)["']""")
    for path in js_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in fetch_call_re.finditer(text):
            target = m.group(2)
            assert target.startswith("/"), (
                f"non-relative fetch target in {path.name}: {target}"
            )


def test_scan_frontend_external_assets_script_runs(tmp_path: Path) -> None:
    """The standalone scan script must report zero findings against the
    repo frontend/ directory."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "scan_frontend_external_assets.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"external_url_count": 0' in result.stdout
