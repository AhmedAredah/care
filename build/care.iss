; Inno Setup script for care (Phase 15.7).
;
; Produces a single .exe installer that lets the operator choose
; between per-user (default, no admin) and machine-wide (admin) install
; via Windows' UAC-style elevation dialog. This is the modern
; ``PrivilegesRequired=lowest`` + ``PrivilegesRequiredOverridesAllowed=dialog``
; pattern Microsoft recommends for sideloaded apps.
;
; The script is invoked four times by ``build_windows.ps1`` to produce
; the four shipping artifacts. Two preprocessor switches drive it:
;
;   /DFlavour=core | ml          which PyInstaller bundle to wrap
;   /DWebView2=online | airgap   which WebView2 redist to embed
;
; Online flavour ships ``MicrosoftEdgeWebview2Setup.exe`` (~2 MB
; bootstrapper that downloads the actual runtime). Airgap flavour
; ships ``MicrosoftEdgeWebView2RuntimeInstallerX64.exe`` (~150 MB
; standalone evergreen runtime — no network needed at install time).
;
; Privacy / offline commitments preserved at install time:
; - The default config that ships in the bundle (and is copied to
;   user-data on first launch by ``runtime_paths.bootstrap_user_data``)
;   already has every cloud/ML/network plugin disabled.
; - The installer never reaches the network in airgap mode.
; - The installer never writes outside the install dir, the per-user
;   start menu / desktop, and the user-data tree (created lazily on
;   first launch, not at install time).
;
; Build (from project root, PowerShell):
;   iscc.exe /DFlavour=core /DWebView2=online  build/care.iss
;   iscc.exe /DFlavour=core /DWebView2=airgap  build/care.iss
;   iscc.exe /DFlavour=ml   /DWebView2=online  build/care.iss
;   iscc.exe /DFlavour=ml   /DWebView2=airgap  build/care.iss

#ifndef Flavour
  #define Flavour "core"
#endif
#ifndef WebView2
  #define WebView2 "online"
#endif

#if Flavour == "core"
  #define AppName        "CARE"
  #define AppDirName     "CARE"
  #define BundleSubdir   "core"
  #define ExeName        "care"
  #define FlavourLabel   "Core"
#elif Flavour == "ml"
  #define AppName        "CARE (ML)"
  #define AppDirName     "CARE-ML"
  #define BundleSubdir   "ml"
  #define ExeName        "care-ml"
  #define FlavourLabel   "ML"
#else
  #error Flavour must be 'core' or 'ml'
#endif

#if WebView2 == "online"
  #define WebView2Installer "MicrosoftEdgeWebview2Setup.exe"
  #define WebView2Label     "Online"
#elif WebView2 == "airgap"
  #define WebView2Installer "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
  #define WebView2Label     "Airgap"
#else
  #error WebView2 must be 'online' or 'airgap'
#endif

#define AppVersion     "0.1.0"
#define AppPublisher   "CARE Project"
#define AppURL         "https://github.com/openCrashExtract/care"
; Stable AppId — DO NOT change between releases. Inno keys uninstall
; entries on this; changing it would orphan existing installs.
#define AppId          "{{7FC84256-27BD-411C-BEFF-C24ECBBE28C2}"
; The PyInstaller spec lays the bundle out under dist/<flavour>/<exename>/.
#define BundleDir      "..\dist\" + BundleSubdir + "\" + ExeName
; Output installer name encodes flavour + webview2 mode so the four
; SKUs are visually distinguishable in releases/.
#define OutputBaseName "CARE-" + AppVersion + "-" + Flavour + "-" + WebView2 + "-Setup"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppDirName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=..\dist\installers
OutputBaseFilename={#OutputBaseName}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
; Allow the user to choose per-user (no admin) or machine-wide install.
; ``lowest`` means "don't elevate by default" — the dialog page will
; offer admin if the user wants every account to see the app.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
; Suppress sticky default that puts shortcuts on every desktop.
AlwaysShowDirOnReadyPage=yes
; Make uninstall fully clean — leave nothing in user data unless
; the operator opts in (we never delete user data on uninstall by
; default; their config + jobs survive an upgrade-by-uninstall).

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; The PyInstaller bundle. ``recursesubdirs`` walks the onedir layout.
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; WebView2 runtime installer — bundled so we can guarantee install
; even on a host that hasn't seen one. Online flavour ships the small
; bootstrapper; airgap ships the full runtime so it works offline.
Source: "redist\{#WebView2Installer}"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}.exe"; IconFilename: "{app}\{#ExeName}.exe"; Tasks: startmenuicon
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}.exe"; IconFilename: "{app}\{#ExeName}.exe"; Tasks: desktopicon

[Run]
; Install WebView2 BEFORE launching the app, but only if it isn't
; already present. ``InstallWebView2Required()`` (Pascal Script below)
; reads the registry to decide.
;
; Switches:
;   /silent /install   — both online bootstrapper and standalone
;                        runtime accept these. No UI flicker for the
;                        operator during install.
Filename: "{tmp}\{#WebView2Installer}"; Parameters: "/silent /install"; \
  StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; \
  Check: InstallWebView2Required; Flags: waituntilterminated
; Optional: launch the app at the end of setup. The user can untick.
Filename: "{app}\{#ExeName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Leave user data intact — config, secrets, jobs, exports all live
; under %LOCALAPPDATA%\CARE and the user's Documents
; folder. The operator can delete these manually if they want a
; full wipe; we never do it for them on uninstall (they may be
; reinstalling to upgrade).

[Code]
{
  WebView2 install detection.

  Microsoft documents two registry keys for "is the Evergreen runtime
  installed?":
    HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\
      {F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}\pv
    HKCU\SOFTWARE\Microsoft\EdgeUpdate\Clients\
      {F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}\pv

  Either being present (and non-empty) means the runtime is installed
  for the current user OR machine-wide. Skip the redist run in that
  case.
}
function InstallWebView2Required(): Boolean;
var
  Version: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') then
    Result := False
  else if RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') then
    Result := False;
end;
