# Windows deployment

This guide covers the four shipping installer variants for
care on Windows, the file locations they use, how to
upgrade/uninstall, and how to build them from source.

The Linux/macOS deployment story (run from a checkout via `uv run` or
`python -m care.cli`) is documented separately in
[`deployment.md`](deployment.md). This document is Windows-specific.

## Choosing an installer

Six artifacts are published per release. Pick by **flavour** (which
plugins ship with the bundle) and **package format**.

| File pattern | Flavour | Format | WebView2 redist | Use when |
|---|---|---|---|---|
| `CARE-*-core-online-Setup.exe` | Core | .exe (Inno) | Online bootstrapper (~2 MB) | Default desktop install on a connected workstation |
| `CARE-*-core-airgap-Setup.exe` | Core | .exe (Inno) | Standalone runtime (~150 MB) | Air-gapped or restricted-network workstation |
| `CARE-*-ml-online-Setup.exe`   | ML   | .exe (Inno) | Online bootstrapper | You need the optional Hugging Face models (Piiranha, RoBERTa-NER, Kosmos-2.5, LayoutLM, hf_local) |
| `CARE-*-ml-airgap-Setup.exe`   | ML   | .exe (Inno) | Standalone runtime | ML flavour on an air-gapped host |
| `CARE-*-core.msi`              | Core | .msi (WiX)  | Prerequisite (admin pre-stages) | Enterprise SCCM/Intune deployment |
| `CARE-*-ml.msi`                | ML   | .msi (WiX)  | Prerequisite | Enterprise (ML) |

### Flavour: Core vs ML

**Core (default)** — the slim build (~80–120 MB onedir) with:

- FastAPI + uvicorn server
- pywebview desktop wrapper
- pypdfium2 PDF rendering
- The regex + Presidio PII chain
- Mock OCR / VLM / PII / LLM providers (for testing the pipeline)

Cloud LLMs and heavyweight Hugging Face models are *not* installed.
This is the right choice for the air-gap-friendly default.

**ML** — adds:

- `torch` + `transformers` (~2 GB onedir total)
- The optional Piiranha PII plugin (still disabled by default — must
  be enabled via Settings, and the operator owns the licence-review
  responsibility)
- The Kosmos-2.5 / LayoutLM document-AI plugins (still disabled by
  default; loaded only from local model files)
- The `hf_local` LLM provider

The ML flavour does **not** enable any of these models by default.
Defaults still meet GOVERNANCE.md: offline, no cloud, no telemetry.
What changes is that the model wheels are *available* if the operator
later decides to enable them in Settings.

### Format: .exe (Inno Setup) vs .msi (WiX)

| Aspect | .exe (Inno) | .msi (WiX) |
|---|---|---|
| Per-user install (no admin) | ✅ default — UAC prompts only if user elevates | ❌ per-machine only |
| Per-machine install (admin) | ✅ via the install-mode dialog | ✅ default |
| WebView2 runtime | bundled (online or airgap) | prerequisite — admin pre-stages |
| Group policy / SCCM / Intune | not standard | ✅ built for this |
| Group install at scale | manual | `msiexec /i ... /qn ALLUSERS=1` |
| Code signing | one signed .exe per SKU | one signed .msi per flavour |

If you're a single user installing on your own workstation, use the
.exe. If you're a Windows admin pushing out hundreds of seats, use
the .msi.

## Where files live (per-user install)

The installer puts the application binaries here:

```
%LOCALAPPDATA%\Programs\CARE\         (per-user)
%ProgramFiles%\CARE\                  (admin / MSI)
```

All operator-facing data (config, secrets, models, jobs, logs) lives
under the user-data tree, which is created lazily on first launch
(not at install time):

```
%LOCALAPPDATA%\CARE\
  config\
    config.yaml                 the active configuration
    config.YYYY-MM-DD_HHMMSS.bak.yaml   GUI-created backups (Phase 13.3)
  secrets\
    secrets.yaml                Cloud LLM API keys etc. (chmod-equivalent: ACL'd to current user)
  templates\
    <state>\<template>.yaml     User-authored / -copied templates
  models\
    <provider>\<model>\         Local model files (you supply these)
  work\
    jobs\<job-id>\              Per-job working dir (rendered pages, OCR cache)
  logs\
    care.log      Rotating log (5 × 5 MB)
```

Public exports go into the user's Documents folder so they're easy to
find and share:

```
%USERPROFILE%\Documents\CARE\exports\<job-id>\
  diagram.redacted.png
  narrative.redacted.txt
  narrative.redacted.json
  manifest.json
  qa.json
```

The OneDrive case is handled correctly: if `Documents` is redirected
to OneDrive, the exports follow it (Win32 `SHGetKnownFolderPath` is
used, not a hard-coded `%USERPROFILE%\Documents` path).

## First-launch bootstrap

On the first launch the app:

1. Resolves `user_data_root()` per the table above.
2. Creates each subdirectory if missing.
3. Copies the seed `config.yaml` and the bundled `templates/` tree out
   of the install dir into the user-data tree. Existing user files are
   never overwritten — the bootstrap is idempotent.
4. Attaches a rotating-file log handler at
   `%LOCALAPPDATA%\CARE\logs\care.log`.
5. Starts uvicorn on `127.0.0.1:7860` (loopback only) on a background
   thread, then opens a pywebview window pointing at it.

There is no internet activity at any step. Cloud LLM providers, the
Piiranha plugin, the Kosmos-2.5/LayoutLM plugins, and the hf_local
provider are all disabled in the seed config; they remain that way
until the operator enables them in Settings.

## Upgrading

Both formats support in-place upgrade.

- **.exe** — re-running a newer Setup.exe upgrades the existing
  install. The user-data tree (config, secrets, jobs, exports) is
  preserved across upgrades.
- **.msi** — `msiexec /i CARE-*-core.msi /qn` over the
  top of an existing install upgrades it via the standard
  `MajorUpgrade` mechanism. The `UpgradeCode` is stable per flavour,
  so successive releases roll forward; downgrades are blocked with a
  clear error.

Switching flavours (core ⇄ ml) requires uninstalling the old SKU
first, because the Inno `AppId` and the WiX `UpgradeCode` differ
between flavours. User data survives the switch.

## Uninstalling

The uninstaller removes only the install-dir binaries and the start-
menu / desktop shortcuts. It does **not** touch the user-data tree
under `%LOCALAPPDATA%\CARE` or the exports under
`%USERPROFILE%\Documents\CARE\`. Two reasons:

1. The most common reason to uninstall is to upgrade or to swap
   flavours; blowing away the operator's config and jobs would be
   surprising.
2. Even on a deliberate full uninstall, the user-data tree is the
   operator's data, and we let them delete it manually if they
   want a complete wipe.

To remove user data:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\CARE"
Remove-Item -Recurse -Force "$env:USERPROFILE\Documents\CARE"
```

## WebView2 runtime

care uses [Microsoft Edge WebView2] for the desktop
window. This is part of every Windows 11 install and is shipped with
modern Edge updates on Windows 10. In practice nearly every Windows
host already has it.

If WebView2 is missing:

- **.exe online** — the bundled `MicrosoftEdgeWebview2Setup.exe`
  bootstrapper downloads it from Microsoft at install time (~2 MB
  download).
- **.exe airgap** — the bundled
  `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` installs the full
  runtime offline.
- **.msi** — install fails with an actionable message. Admins should
  pre-stage WebView2 (Microsoft publishes both the bootstrapper and a
  fixed-version runtime as MSIs at
  <https://developer.microsoft.com/microsoft-edge/webview2/>).

[Microsoft Edge WebView2]: https://developer.microsoft.com/microsoft-edge/webview2/

## Code signing

All shipping artifacts are signed by the [SignPath Foundation], a
free OV code-signing service for open-source projects. Verify a
download by right-clicking the .exe / .msi → Properties → Digital
Signatures and confirming the signer is `SignPath Foundation`.

[SignPath Foundation]: https://signpath.io/foundation

If you build from source (see below), the unsigned artifacts will
trigger a Windows SmartScreen warning the first time they're run.
This is expected for any unsigned installer.

## Building installers from source

Prerequisites (one-time):

```powershell
# Python + uv
winget install astral-sh.uv

# Inno Setup 6 (for the .exe installers)
winget install JRSoftware.InnoSetup

# WiX Toolset 6 (for the .msi installers)
dotnet tool install --global wix

# Optional: PowerShell 7 for the build orchestrator
winget install Microsoft.PowerShell
```

Build everything from a project checkout:

```powershell
# 1. Sync deps
uv sync                  # for the core flavour
uv sync --extra ml       # for the ml flavour (re-sync between flavours)

# 2. Install PyInstaller (not a runtime dep — only for builds)
uv pip install pyinstaller

# 3. Run the orchestrator. Builds onedir bundles, then optionally
#    Inno .exe installers and/or WiX .msi installers.
pwsh -File build/build_windows.ps1                          # bundles only
pwsh -File build/build_windows.ps1 -Installers              # + 4 .exe SKUs
pwsh -File build/build_windows.ps1 -Msi                     # + 2 .msi SKUs
pwsh -File build/build_windows.ps1 -Installers -Msi -Clean  # everything, fresh
```

Outputs land in:

```
dist/core/care/         core onedir bundle
dist/ml/care-ml/        ml onedir bundle
dist/installers/*.exe                 four .exe installers
dist/installers/*.msi                 two .msi installers
```

The CI workflow (`.github/workflows/windows-build.yml`) does the same
thing on every tag push, then submits each artifact to SignPath
Foundation for signing before attaching them to a GitHub Release.

## Troubleshooting

**The app won't start; the window opens then closes.**
Check `%LOCALAPPDATA%\CARE\logs\care.log`.
The most common cause is a missing WebView2 runtime on Windows 10 LTSC
that hasn't been updated; install WebView2 manually from Microsoft.

**SmartScreen says "Windows protected your PC".**
For an unsigned local build, click **More info → Run anyway**. Signed
release builds should not trigger this; if they do, please file an
issue.

**Per-user install fails with "ERROR_INSTALL_PLATFORM_UNSUPPORTED".**
The .msi is per-machine only — re-run as admin, or use the .exe
installer for per-user installs.

**Where do my exports go?**
`%USERPROFILE%\Documents\CARE\exports\<job-id>\` —
unless `Documents` is redirected (e.g. by OneDrive), in which case
exports follow the redirected path. The active path is shown in the
GUI's job-detail page.
