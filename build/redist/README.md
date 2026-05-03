# build/redist — WebView2 redistributables

The Inno Setup installer (`build/care.iss`) bundles one
of two WebView2 redistributables, depending on the build flavour:

- `MicrosoftEdgeWebview2Setup.exe` (~2 MB) — Evergreen Bootstrapper.
  Downloads the latest WebView2 runtime from Microsoft at install time.
  Used by the **online** installer flavour.

- `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` (~150 MB) — Evergreen
  Standalone Installer. Ships the entire runtime; works without network
  access. Used by the **airgap** installer flavour.

These files are **not committed** to the repository. They are downloaded
at build time by the CI workflow (or, locally, by running:

```powershell
pwsh -File build/fetch_webview2.ps1
```

— once that helper exists; for now you can grab them from
<https://developer.microsoft.com/microsoft-edge/webview2/> manually).

This directory is otherwise empty in version control. `.gitignore`
keeps the binaries out so we don't bloat the repo or accidentally
redistribute the runtime under the wrong terms.
