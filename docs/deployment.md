# Deployment

`care` runs on a single Linux host with an offline
Python 3.11 interpreter. There is no clustered or hosted deployment
mode.

## Prerequisites

- Linux x86_64 (other architectures are untested but should work).
- Python 3.11 available at `/usr/bin/python3` or via `pyenv`/`uv`.
- Disk space for the work + export directories. A typical multi-page
  report uses ~10 MB of work-dir during processing and < 200 KB in
  the public export.
- A vetted local copy of any optional model (Piiranha, Kosmos-2.5,
  PaddleOCR, Tesseract `tessdata`).

## Installation steps (offline)

1. **Carry the bundle.** Copy
   `dist/care-<version>.tar.gz` to the air-gapped host.

   ```
   tar -xzf care-<version>.tar.gz
   cd care-<version>
   ```

2. **Verify the bundle.**

   ```
   sha256sum -c checksums.sha256
   ```

3. **Create a venv from the bundled wheelhouse.**

   ```
   python3 -m venv .venv
   . .venv/bin/activate
   pip install --no-index --find-links wheelhouse -e ./app
   ```

4. **Verify offline.**

   ```
   python scripts/verify_no_network.py
   ```

   This must print `"verdict": "PASS"`.

5. **Place model files.** For each provider you intend to enable,
   follow the matching `models/<group>/<provider>/README.md` and
   record checksums:

   ```
   python scripts/compute_model_checksums.py models/document_ai/kosmos-2.5
   ```

6. **Edit `config/config.yaml`.** Default config keeps every optional
   provider disabled. Enable only what you've cleared license-wise.

7. **Run.**

   ```
   python -m care.cli serve --config config/config.yaml
   ```

   By default this binds to `127.0.0.1:7860`. Open
   `http://127.0.0.1:7860/` in a local browser.

## Desktop launcher (Phase 14)

For end-users who would rather double-click an icon than open a
terminal, the `app` subcommand wraps the FastAPI server in a native
window via pywebview. The window only ever loads the loopback URL —
identical trust boundary to the browser-based `serve` flow.

### Per-platform prerequisites

- **Windows**: WebView2 Runtime. Auto-installed on Windows 11 and
  recent Windows 10 by Microsoft Edge. On older / air-gapped Windows
  hosts, install the offline Evergreen Runtime once
  ([download from Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/) —
  carry the MSI on your bundle media). No extra Python deps.
- **macOS**: nothing extra. Cocoa + WebKit are part of the OS.
- **Linux**: GTK 3 + WebKitGTK ≥ 2.22, e.g. on Ubuntu/Debian:

  ```
  sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1
  ```

  On distros where these aren't packaged, use the Qt backend instead:
  `pip install 'pywebview[qt]'`.

### Open the window

```
python -m care.cli app --config config/config.yaml
```

This spawns `serve` on `127.0.0.1:<port>` in the background, polls
`/api/health` until ready, and opens the desktop window. Closing the
window terminates the server subprocess. The WebView cache lives
inside `paths.work_dir/webview-cache` so it is auditable and
cleaned up with the rest of the working tree.

The command has no `--allow-non-loopback` escape hatch on purpose;
non-loopback hosts are rejected before any subprocess starts.

### Create a desktop icon (optional)

```
python -m care.cli install-shortcut --config /abs/path/config.yaml
```

This drops the right launcher on the user's Desktop:

- Windows: `CARE.lnk`
- macOS: `CARE.app` (bundle)
- Linux: `care.desktop` (and a copy under
  `$XDG_DATA_HOME/applications/`)

Each launcher invokes `python -m care.cli app` with the
right working directory and config path. Re-running
`install-shortcut` overwrites cleanly; `uninstall-shortcut` removes
it. If you don't pass `--icon`, the bundled placeholder under
`assets/icon.{ico,icns,png}` is used.

## Running batch jobs (no UI)

```
python -m care.cli process /path/to/inputs \
    --config config/config.yaml \
    --work-dir /path/to/work \
    --export-dir /path/to/exports \
    --templates-dir templates
```

`--fail-on-block` returns non-zero if the QA gate blocked any report.

## Health checks

- `curl http://127.0.0.1:7860/api/health` → `{"status":"ok",…}`
- `curl http://127.0.0.1:7860/api/offline/status` → guard + HF env audit
- `python scripts/verify_no_network.py` (anytime, offline-safe)

## Updating

1. Carry a new tarball across.
2. Verify checksums, install into a fresh venv beside the existing one.
3. Validate against your synthetic fixtures.
4. Cut over by changing the path of the systemd unit (or whatever
   wrapper you use) — there is no in-place upgrade or auto-update.
