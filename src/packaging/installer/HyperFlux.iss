#define AppName "HyperFlux"
#define AppVersion GetEnv("HYPERFLUX_VERSION")
#if AppVersion == ""
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
AppId={{B1B48011-39D4-43F3-9DE0-93BE1E21717B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=HaveFun2012
DefaultDirName={autopf}\HyperFlux
DefaultGroupName=HyperFlux
OutputDir=..\..\dist
OutputBaseFilename=HyperFlux-Setup
SetupIconFile=..\hyperflux.ico
UninstallDisplayIcon={app}\HyperFlux.exe
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\..\dist\HyperFlux\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\..\LICENSES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\HyperFlux"; Filename: "{app}\HyperFlux.exe"
Name: "{autodesktop}\HyperFlux"; Filename: "{app}\HyperFlux.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HyperFlux.exe"; Description: "Launch HyperFlux"; Flags: postinstall nowait skipifsilent
; In-app updates run this installer silently; reopen HyperFlux when it's done.
Filename: "{app}\HyperFlux.exe"; Flags: nowait; Check: WizardSilent
