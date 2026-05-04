# PyInstaller spec for care (Phase 15.6).
#
# Two flavours are produced from this single spec, selected by the
# ``OCE_FLAVOUR`` environment variable:
#
#   - ``core`` (default) — slim runtime: FastAPI + pywebview + pypdfium2
#     + ruamel.yaml + the regex/Presidio PII chain. ~80–120 MB onedir.
#   - ``ml`` — adds torch + transformers (Piiranha, RoBERTa-NER,
#     OpenAI Privacy Filter, Kosmos-2.5, LayoutLM, hf_local LLM).
#     ~2 GB onedir, but everything ships inside the bundle so the
#     user can opt in to those models without a separate install.
#
# We deliberately use ``onedir`` rather than ``onefile``:
#   - Fast startup (no per-launch archive extraction).
#   - The signed artifact is a real .exe + side-by-side DLLs, which
#     Windows code-signing tools and SmartScreen reputation handle
#     natively. Onefile signs the bootstrapper, not the app.
#   - SignPath Foundation accepts onedir directly.
#
# Build:
#   ``pyinstaller build/care.spec``  (sets OCE_FLAVOUR=core
#   if unset — see ``build_windows.ps1`` for the orchestrator that
#   builds both flavours.)
# pylint: disable=undefined-variable
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# ---------------------------------------------------------------------------
# Paths and flavour selection
# ---------------------------------------------------------------------------

# SPECPATH is provided by PyInstaller — the directory containing this spec.
PROJECT_ROOT = Path(SPECPATH).parent.resolve()  # type: ignore[name-defined]
RUNNER = str(PROJECT_ROOT / "build" / "runner.py")
ICON = str(PROJECT_ROOT / "assets" / "icon.ico")

FLAVOUR = os.environ.get("OCE_FLAVOUR", "core").strip().lower()
if FLAVOUR not in ("core", "ml"):
    raise SystemExit(
        f"OCE_FLAVOUR must be 'core' or 'ml' (got {FLAVOUR!r}). "
        "Set the env var before running PyInstaller."
    )

APP_NAME = "care" if FLAVOUR == "core" else "care-ml"

# ---------------------------------------------------------------------------
# Bundled data
# ---------------------------------------------------------------------------
# These ship inside the bundle and are read via ``runtime_paths.bundled_resource_root()``
# at runtime. ``bootstrap_user_data()`` copies the seed config + templates
# from here into the per-user data tree on first launch.

datas: list[tuple[str, str]] = [
    (str(PROJECT_ROOT / "frontend"), "frontend"),
    (str(PROJECT_ROOT / "templates"), "templates"),
    (str(PROJECT_ROOT / "assets"), "assets"),
    (str(PROJECT_ROOT / "config.example.yaml"), "."),
    (str(PROJECT_ROOT / "GOVERNANCE.md"), "."),
    (str(PROJECT_ROOT / "LICENSE"), "."),
]
# Drop entries whose source file doesn't exist (config.example.yaml is
# optional in the dev tree; the build script ensures it's generated
# before invoking PyInstaller).
datas = [(src, dst) for src, dst in datas if Path(src).exists()]

# Collect package data files for libraries that ship resources.
datas += collect_data_files("pypdfium2")
datas += collect_data_files("ruamel.yaml")
datas += collect_data_files("webview")  # pywebview JS bridge files

# ---------------------------------------------------------------------------
# Hidden imports
# ---------------------------------------------------------------------------
# Provider registries import their providers eagerly, so PyInstaller's
# static analysis catches them. We still hand-list the package roots so
# that any future lazy registration is covered.

hiddenimports: list[str] = []
hiddenimports += collect_submodules("care")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("pydantic")
# ruamel.yaml uses metadata-driven plugin loading.
hiddenimports += collect_submodules("ruamel.yaml")

if FLAVOUR == "ml":
    # Pulled in only for the ML flavour. ``transformers`` and ``torch``
    # are heavy but their submodules are auto-discovered when present.
    hiddenimports += collect_submodules("transformers")
    hiddenimports += ["torch"]
    # Don't ``collect_submodules('torch')`` — it's enormous and most of
    # it is unused at inference time. PyInstaller's static analysis on
    # the providers is enough for the parts we touch.
else:
    # Core flavour: explicitly drop the ML providers from the bundle so
    # we don't accidentally ship torch/transformers if they're in the
    # build venv.
    pass

# ---------------------------------------------------------------------------
# Excludes
# ---------------------------------------------------------------------------
# Things PyInstaller might pick up transitively that we never want.

excludes: list[str] = [
    # Never ship the dev-only PDF generator (fpdf2 is a test helper).
    "fpdf",
    "fpdf2",
    # Test frameworks.
    "pytest",
    "_pytest",
    # Notebook stack — not used at runtime.
    "IPython",
    "ipykernel",
    "jupyter",
    "jupyterlab",
    "notebook",
    # Other GUI toolkits — pywebview uses the OS WebView, not Qt/Tk.
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "tkinter",
    "wx",
    # Scientific stack pulled in transitively but not needed at runtime
    # for the *core* flavour. Re-allowed in ml.
]

if FLAVOUR == "core":
    excludes += [
        "torch",
        "torchvision",
        "torchaudio",
        "transformers",
        "tokenizers",
        "safetensors",
        "datasets",
        "accelerate",
        "huggingface_hub",
        "scipy",
        "sklearn",
        "matplotlib",
    ]

# ---------------------------------------------------------------------------
# Analysis / build steps
# ---------------------------------------------------------------------------

block_cipher = None

a = Analysis(  # type: ignore[name-defined]  # noqa: F821
    [RUNNER],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # type: ignore[name-defined]  # noqa: F821

exe = EXE(  # type: ignore[name-defined]  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trips antivirus; harms SmartScreen reputation.
    console=False,  # GUI app — no console window on launch.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if Path(ICON).exists() else None,
    version=None,  # versioninfo .txt can be added at signing time.
)

coll = COLLECT(  # type: ignore[name-defined]  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
