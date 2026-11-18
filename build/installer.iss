; Inno Setup script - tao bo cai dat. Build Windows.bat tu chay neu may co Inno Setup 6.
#define AppName "Video AI - Mr. Huynh"
#define AppVersion "1.0.0"
#define AppExe "VideoAI-MrHuynh.exe"

[Setup]
AppId={{6C1E2B5A-8E0F-4F7B-9B8E-2F6A7A1D9C11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Mr. Huynh
DefaultDirName={autopf}\VideoAI-MrHuynh
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=VideoAI-MrHuynh-Setup-{#AppVersion}
SetupIconFile=..\videoai\assets\icon.ico
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong ngoai Desktop"; GroupDescription: "Tuy chon:"

[Files]
Source: "..\dist\VideoAI-MrHuynh\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Mo {#AppName}"; Flags: nowait postinstall skipifsilent
