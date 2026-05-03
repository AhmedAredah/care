"""Policy tests for the Windows frozen-build assets (Phase 15.6).

These artifacts are not exercised by the Linux CI pytest run on every
push, but they MUST stay in the tree so the Windows build job can
consume them. The tests below check shape, not behaviour:

- the runner script exists and parses,
- the PyInstaller spec exists, parses, and honours the
  ``OCE_FLAVOUR`` env var (we read its source to confirm),
- the build orchestrator script exists.

A regression that drops one of these files would break the release
pipeline silently otherwise.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_frozen_runner_script_present_and_parses() -> None:
    runner = REPO_ROOT / "build" / "runner.py"
    assert runner.exists(), "build/runner.py is the frozen entry; cannot be removed"
    ast.parse(runner.read_text(encoding="utf-8"))


def test_pyinstaller_spec_present_and_parses() -> None:
    spec = REPO_ROOT / "build" / "care.spec"
    assert spec.exists(), "build/care.spec must ship for Windows builds"
    ast.parse(spec.read_text(encoding="utf-8"))


def test_pyinstaller_spec_supports_two_flavours() -> None:
    """The spec MUST honour OCE_FLAVOUR with both 'core' and 'ml'.

    The Windows build job runs PyInstaller twice with different
    ``OCE_FLAVOUR`` values. Anything that breaks that rule (e.g. a
    rewrite that hard-codes a single flavour) would silently drop the
    ml installer.
    """
    spec_text = (REPO_ROOT / "build" / "care.spec").read_text(encoding="utf-8")
    assert "OCE_FLAVOUR" in spec_text
    assert '"core"' in spec_text or "'core'" in spec_text
    assert '"ml"' in spec_text or "'ml'" in spec_text


def test_pyinstaller_spec_excludes_dev_only_packages_in_core() -> None:
    """Defence in depth: core flavour must not bundle torch/transformers
    or pytest. A regression here would balloon the slim installer."""
    spec_text = (REPO_ROOT / "build" / "care.spec").read_text(encoding="utf-8")
    for forbidden in ("pytest", "torch", "transformers"):
        assert forbidden in spec_text, (
            f"core-flavour exclude list must keep blocking {forbidden!r}"
        )


def test_build_windows_orchestrator_present() -> None:
    ps1 = REPO_ROOT / "build" / "build_windows.ps1"
    assert ps1.exists(), "build/build_windows.ps1 wires the two-flavour build"
    text = ps1.read_text(encoding="utf-8")
    assert "OCE_FLAVOUR" in text
    assert "pyinstaller" in text.lower()


def test_runner_dispatches_to_app_subcommand_by_default() -> None:
    """Double-clicking the .exe must land in the desktop GUI, not in
    the bare CLI parser. The runner enforces this by injecting ``app``
    when no argv is supplied."""
    runner_text = (REPO_ROOT / "build" / "runner.py").read_text(encoding="utf-8")
    assert '"app"' in runner_text or "'app'" in runner_text
    assert "configure_logging_for_frozen" in runner_text
    assert "bootstrap_user_data" in runner_text


def test_inno_setup_script_present_and_supports_four_skus() -> None:
    iss = REPO_ROOT / "build" / "care.iss"
    assert iss.exists(), "build/care.iss must ship for Windows installer"
    text = iss.read_text(encoding="utf-8")
    # Two preprocessor switches must drive the four-SKU build.
    assert "Flavour" in text
    assert "WebView2" in text
    assert "core" in text and "ml" in text
    assert "online" in text and "airgap" in text


def test_inno_setup_supports_per_user_and_admin_install() -> None:
    """Per-user-or-admin choice MUST be exposed via Inno's dialog mode.

    A regression here would force admin (which OSS users won't have)
    or hard-bind to per-user (which enterprise wouldn't accept)."""
    text = (REPO_ROOT / "build" / "care.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "PrivilegesRequiredOverridesAllowed=dialog" in text


def test_inno_setup_pins_stable_appid() -> None:
    """The AppId is the upgrade key; if it ever changes a future
    release will install side-by-side instead of upgrading. Leave a
    test in the way of any drive-by edit."""
    text = (REPO_ROOT / "build" / "care.iss").read_text(encoding="utf-8")
    assert "7FC84256-27BD-411C-BEFF-C24ECBBE28C2" in text


def test_inno_setup_does_not_delete_user_data_on_uninstall() -> None:
    """User config + jobs + exports must survive an uninstall — the
    common case is uninstall-then-reinstall to upgrade between
    flavours, and we won't blow away their work for them."""
    text = (REPO_ROOT / "build" / "care.iss").read_text(encoding="utf-8")
    # The [UninstallDelete] section either is empty or contains only
    # comments. We check the negative: no ``Type: filesandordirs;
    # Name: {userappdata}`` or similar entry.
    assert "{userappdata}" not in text
    assert "{localappdata}" not in text
    assert "{userdocs}" not in text


def test_webview2_redist_directory_present() -> None:
    """The .iss script references redist/{installer}.exe at compile
    time. The directory + README must exist even though the binaries
    themselves are gitignored."""
    redist_dir = REPO_ROOT / "build" / "redist"
    assert redist_dir.exists() and redist_dir.is_dir()
    assert (redist_dir / "README.md").exists()


def test_wix_msi_source_present_and_supports_two_flavours() -> None:
    """The WiX 6 source file must ship for the enterprise MSI build.
    Both flavours share one .wxs driven by ``-d Flavour=...``."""
    wxs = REPO_ROOT / "build" / "care.wxs"
    assert wxs.exists(), "build/care.wxs must ship for MSI builds"
    text = wxs.read_text(encoding="utf-8")
    assert "Flavour" in text
    assert "core" in text and "ml" in text
    # Each flavour must pin its own UpgradeCode — losing this means
    # MSI upgrades stop working between releases.
    assert "8B12C9A4-3E7D-4A5F-9E22-7A1F8C66D314" in text  # core
    assert "C7B19A82-4F61-4D7E-AB30-D4F9F1ED4C05" in text  # ml


def test_wix_msi_treats_webview2_as_prerequisite() -> None:
    """The MSI fails the install with a clear message if WebView2 is
    missing, rather than bundling 150 MB of redistributable. That's
    the right model for SCCM/Intune: admins pre-stage WebView2."""
    text = (REPO_ROOT / "build" / "care.wxs").read_text(encoding="utf-8")
    assert "WEBVIEW2_HKLM" in text
    assert "Launch Condition" in text or "<Launch" in text
    # Must NOT bundle the redistributable.
    assert "MicrosoftEdgeWebView2RuntimeInstallerX64.exe" not in text


def test_wix_msi_uses_per_machine_scope() -> None:
    """MSI variant is the enterprise/admin path. Per-user lives in
    the Inno .exe variant. ``Scope="perMachine"`` enforces this."""
    text = (REPO_ROOT / "build" / "care.wxs").read_text(encoding="utf-8")
    assert 'Scope="perMachine"' in text


def test_windows_build_workflow_present() -> None:
    """The release-build workflow must exist for tag-push releases."""
    wf = REPO_ROOT / ".github" / "workflows" / "windows-build.yml"
    assert wf.exists()
    text = wf.read_text(encoding="utf-8")
    assert "tags:" in text
    assert "v*" in text
    # Must run both flavours.
    assert "core" in text and "ml" in text
    # Must build all three artifact families.
    assert "Inno Setup" in text or "innosetup" in text
    assert "wix" in text.lower()
    # Must support signing via SignPath Foundation.
    assert "signpath" in text.lower()


def test_windows_tests_workflow_runs_on_pull_request() -> None:
    """PR-time Windows checks must run on every PR — light enough to
    not blow up the queue, but enough to catch Windows-only regressions
    in path / ACL / logging code."""
    wf = REPO_ROOT / ".github" / "workflows" / "windows-tests.yml"
    assert wf.exists()
    text = wf.read_text(encoding="utf-8")
    assert "pull_request" in text
    assert "windows-latest" in text


def test_windows_deployment_docs_present() -> None:
    """The Windows-specific deployment story must be documented for
    operators / IT admins."""
    doc = REPO_ROOT / "docs" / "deployment-windows.md"
    assert doc.exists()
    text = doc.read_text(encoding="utf-8")
    # Must explain the four .exe SKUs, the two .msi flavours, and
    # the file-location convention.
    for needle in (
        "core",
        "ml",
        "online",
        "airgap",
        ".msi",
        "%LOCALAPPDATA%",
        "WebView2",
        "SignPath",
        "uninstall",
    ):
        assert needle in text or needle.lower() in text.lower(), (
            f"deployment-windows.md must mention {needle!r}"
        )


def test_windows_build_workflow_does_not_leak_secrets() -> None:
    """Defence: the SignPath secrets must come from the secrets
    context, never inlined. A regression here could leak a token
    on every build."""
    text = (REPO_ROOT / ".github" / "workflows" / "windows-build.yml").read_text(encoding="utf-8")
    assert "secrets.SIGNPATH_API_TOKEN" in text
    # Don't ship a literal token anywhere.
    assert "api-token: signpath_" not in text.lower()
    assert "BEGIN PRIVATE KEY" not in text
    assert "BEGIN RSA PRIVATE KEY" not in text
