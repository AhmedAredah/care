# Fetch WebView2 redistributables (Phase 15.7).
#
# Downloads the two installers consumed by the Inno Setup installer:
#   - MicrosoftEdgeWebview2Setup.exe          (~2 MB, online bootstrapper)
#   - MicrosoftEdgeWebView2RuntimeInstallerX64.exe  (~150 MB, standalone)
#
# Stable Microsoft URLs ("evergreen" forever-redirect) per:
#   https://developer.microsoft.com/microsoft-edge/webview2/
#
# Skips downloads that already exist with a non-zero size.
[CmdletBinding()]
param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RedistDir = "$PSScriptRoot/redist"
New-Item -ItemType Directory -Force -Path $RedistDir | Out-Null

$Files = @(
    @{
        Name = "MicrosoftEdgeWebview2Setup.exe"
        Url  = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
    },
    @{
        Name = "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
        Url  = "https://go.microsoft.com/fwlink/?linkid=2124701"
    }
)

foreach ($f in $Files) {
    $Dest = Join-Path $RedistDir $f.Name
    if ((Test-Path $Dest) -and (-not $Force) -and ((Get-Item $Dest).Length -gt 0)) {
        Write-Host "  exists: $($f.Name)"
        continue
    }
    Write-Host "Downloading $($f.Name)..."
    Invoke-WebRequest -Uri $f.Url -OutFile $Dest -UseBasicParsing
    Write-Host "  → $Dest"
}

Write-Host "WebView2 redistributables ready in $RedistDir"
