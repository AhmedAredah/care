# Windows build orchestrator (Phase 15.6).
#
# Builds one or both PyInstaller flavours and lays them out under
# ``dist/`` so ``build/care.iss`` (Phase 15.7) can pick
# them up directly.
#
# Usage (from project root):
#   pwsh -File build/build_windows.ps1                  # both flavours
#   pwsh -File build/build_windows.ps1 -Flavour core    # core only
#   pwsh -File build/build_windows.ps1 -Flavour ml      # ml only
#   pwsh -File build/build_windows.ps1 -Clean           # wipe dist/ build/work first
#
# The script does NOT install dependencies — it expects ``uv sync``
# (and, for the ml flavour, ``uv sync --extra ml``) to have been run
# already. CI runs both syncs against separate venvs and invokes this
# script twice with -Flavour.
[CmdletBinding()]
param(
    [ValidateSet("core", "ml", "both")]
    [string]$Flavour = "both",
    [switch]$Clean,
    [switch]$Installers,           # also run Inno Setup (.exe SKUs) at the end
    [switch]$Msi,                  # also build the WiX MSI variants
    [switch]$SkipPyInstaller       # only build installers (assumes dist/ is already populated)
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot/..").Path
Set-Location $ProjectRoot

Write-Host "care Windows build" -ForegroundColor Cyan
Write-Host "  project root: $ProjectRoot"
Write-Host "  flavour:      $Flavour"

if ($Clean) {
    Write-Host "Cleaning dist/ and build/work/..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$ProjectRoot/dist"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue "$ProjectRoot/build/work"
}

# Ensure config.example.yaml exists for the bundle. We commit a real
# default elsewhere; here we write a small fallback if it's missing so
# the bundle still has a seed config.
$ConfigExample = Join-Path $ProjectRoot "config.example.yaml"
if (-not (Test-Path $ConfigExample) -and (Test-Path "$ProjectRoot/config.yaml")) {
    Copy-Item "$ProjectRoot/config.yaml" $ConfigExample
    Write-Host "  seeded config.example.yaml from config.yaml"
}

function Invoke-PyInstaller {
    param([string]$F)

    Write-Host ""
    Write-Host "=== Building flavour: $F ===" -ForegroundColor Green
    $env:OCE_FLAVOUR = $F

    $WorkPath = "$ProjectRoot/build/work/$F"
    $DistPath = "$ProjectRoot/dist/$F"
    New-Item -ItemType Directory -Force -Path $WorkPath, $DistPath | Out-Null

    # ``uv run`` keeps us inside the project venv without requiring it
    # to be activated in the current shell.
    & uv run --no-sync pyinstaller `
        --noconfirm `
        --workpath $WorkPath `
        --distpath $DistPath `
        "$ProjectRoot/build/care.spec"

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for flavour '$F' (exit $LASTEXITCODE)"
    }

    $AppName = if ($F -eq "core") { "care" } else { "care-ml" }
    $Exe = Join-Path $DistPath "$AppName/$AppName.exe"
    if (-not (Test-Path $Exe)) {
        throw "Expected exe not found: $Exe"
    }
    Write-Host "  built: $Exe" -ForegroundColor Green
}

if (-not $SkipPyInstaller) {
    if ($Flavour -eq "both" -or $Flavour -eq "core") {
        Invoke-PyInstaller -F "core"
    }
    if ($Flavour -eq "both" -or $Flavour -eq "ml") {
        Invoke-PyInstaller -F "ml"
    }
}

if ($Installers) {
    Write-Host ""
    Write-Host "=== Building installers ===" -ForegroundColor Green

    # iscc.exe lives at one of two stable locations; let the user
    # override via $env:ISCC if they have a non-default install.
    $Iscc = $env:ISCC
    if (-not $Iscc) {
        $Candidates = @(
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
        )
        $Iscc = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $Iscc) {
        throw "ISCC.exe not found. Install Inno Setup 6 or set `$env:ISCC."
    }
    Write-Host "  iscc: $Iscc"

    # Make sure the WebView2 redistributables are in place. The Inno
    # script will fail with "missing source file" if they aren't.
    # fetch_webview2.ps1 has $ErrorActionPreference=Stop, so any real
    # failure bubbles up as a PowerShell exception under our own
    # ErrorActionPreference=Stop. We deliberately do NOT check
    # $LASTEXITCODE here — that variable is only updated by external
    # native commands; a .ps1 invocation leaves it carrying whatever
    # the previous external call set (e.g. PyInstaller's exit code),
    # which produces spurious "WebView2 fetch failed" throws.
    & "$ProjectRoot/build/fetch_webview2.ps1"

    $Flavours = if ($Flavour -eq "both") { @("core", "ml") } else { @($Flavour) }
    foreach ($F in $Flavours) {
        foreach ($WV in @("online", "airgap")) {
            Write-Host "  building installer: $F / $WV" -ForegroundColor Yellow
            & $Iscc /Q "/DFlavour=$F" "/DWebView2=$WV" "$ProjectRoot/build/care.iss"
            if ($LASTEXITCODE -ne 0) {
                throw "iscc failed for $F / $WV (exit $LASTEXITCODE)"
            }
        }
    }
    Write-Host "  installers in: dist/installers/" -ForegroundColor Green
}

if ($Msi) {
    Write-Host ""
    Write-Host "=== Building WiX MSI variants ===" -ForegroundColor Green

    # ``wix.exe`` is provided by the dotnet global tool ``wix``. The
    # CI workflow installs it via ``dotnet tool install --global wix``.
    $Wix = Get-Command wix -ErrorAction SilentlyContinue
    if (-not $Wix) {
        throw "wix.exe not on PATH. Install with 'dotnet tool install --global wix'."
    }

    # Convert plain-text LICENSE to RTF — WixUI_Minimal renders an RTF
    # license sheet on the welcome page. We do a trivial wrap rather
    # than depending on Word/wkhtmltopdf.
    $LicensePlain = Join-Path $ProjectRoot "LICENSE"
    $LicenseRtf = Join-Path $ProjectRoot "LICENSE.rtf"
    if (-not (Test-Path $LicenseRtf) -or ((Get-Item $LicensePlain).LastWriteTime -gt (Get-Item $LicenseRtf).LastWriteTime)) {
        $body = (Get-Content $LicensePlain -Raw) -replace "\\", "\\\\" -replace "`r?`n", "\par "
        @"
{\rtf1\ansi\deff0
$body
}
"@ | Set-Content -Encoding ASCII $LicenseRtf
        Write-Host "  generated LICENSE.rtf"
    }

    $Version = "0.1.0"   # keep in sync with pyproject.toml [project].version
    $InstallersDir = Join-Path $ProjectRoot "dist\installers"
    New-Item -ItemType Directory -Force -Path $InstallersDir | Out-Null

    $Flavours = if ($Flavour -eq "both") { @("core", "ml") } else { @($Flavour) }
    foreach ($F in $Flavours) {
        $ExeName = if ($F -eq "core") { "care" } else { "care-ml" }
        $BundleDir = "$ProjectRoot\dist\$F\$ExeName"
        if (-not (Test-Path $BundleDir)) {
            throw "Bundle dir missing: $BundleDir (run without -SkipPyInstaller first)."
        }
        $MsiOut = Join-Path $InstallersDir "CARE-$Version-$F.msi"
        Write-Host "  building MSI: $F → $MsiOut" -ForegroundColor Yellow
        & wix build "$ProjectRoot\build\care.wxs" `
            -d "Flavour=$F" `
            -d "Version=$Version" `
            -d "BundleDir=$BundleDir" `
            -d "IconPath=$ProjectRoot\assets\icon.ico" `
            -d "LicenseRtfPath=$ProjectRoot\LICENSE.rtf" `
            -ext WixToolset.UI.wixext `
            -o $MsiOut
        if ($LASTEXITCODE -ne 0) {
            throw "wix build failed for $F (exit $LASTEXITCODE)"
        }
    }
}

Write-Host ""
Write-Host "Build complete." -ForegroundColor Cyan
Write-Host "  dist/core/        → core (slim) onedir"
Write-Host "  dist/ml/          → ml flavour onedir"
if ($Installers) {
    Write-Host "  dist/installers/  → .exe installers (core/ml × online/airgap)"
}
if ($Msi) {
    Write-Host "  dist/installers/  → .msi installers (core/ml)"
}
if (-not $Installers -and -not $Msi) {
    Write-Host ""
    Write-Host "Re-run with -Installers and/or -Msi to also produce setup files."
}
