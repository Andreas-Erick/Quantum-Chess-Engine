; Inno Setup script for the Windows installer. Build the app first (see quantum_chess.spec), then
; from the project root:
;
;     iscc /DAppVersion=1.2.3 desktop\installer.iss
;
; Output: installer\QuantumChess-Setup-<version>.exe. Installs per user without admin rights
; (or for all users, if the user picks that), with a Start menu entry and an uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; The AppId identifies the app across versions, so upgrades replace it. Never change it.
AppId={{A13B2EEE-2C64-4474-82F0-F3B08D164B49}
AppName=Quantum Chess Engine
AppVersion={#AppVersion}
AppPublisher=Andreas Erick
AppPublisherURL=https://github.com/Andreas-Erick/Quantum-Chess
DefaultDirName={autopf}\Quantum Chess Engine
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
OutputDir=..\installer
OutputBaseFilename=QuantumChess-Setup-{#AppVersion}
UninstallDisplayIcon={app}\QuantumChess.exe
SetupIconFile=icon.ico
; The app's data lives in the user's AppData (see [UninstallDelete]); that's intended.
UsedUserAreasWarning=no
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\QuantumChess\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Clear the previous version's bundled libraries, so an upgrade never mixes old and new files.
Type: filesandordirs; Name: "{app}\_internal"
; Shortcuts from before the app was renamed (0.8.1 and earlier), so an upgrade leaves no duplicates.
Type: files; Name: "{autoprograms}\Quantum Chess.lnk"
Type: files; Name: "{autodesktop}\Quantum Chess.lnk"

[UninstallDelete]
; What the app saved: browser storage (finished lessons), the seeds of joined games, the log.
; Nothing in it is useful without the app, so uninstalling leaves nothing behind.
Type: filesandordirs; Name: "{userappdata}\QuantumChess"

[Icons]
Name: "{autoprograms}\Quantum Chess Engine"; Filename: "{app}\QuantumChess.exe"
Name: "{autodesktop}\Quantum Chess Engine"; Filename: "{app}\QuantumChess.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\QuantumChess.exe"; Description: "{cm:LaunchProgram,Quantum Chess Engine}"; Flags: nowait postinstall skipifsilent
