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
AppName=Quantum Chess
AppVersion={#AppVersion}
AppPublisher=Andreas Erick
AppPublisherURL=https://github.com/Andreas-Erick/Quantum-Chess
DefaultDirName={autopf}\Quantum Chess
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
OutputDir=..\installer
OutputBaseFilename=QuantumChess-Setup-{#AppVersion}
UninstallDisplayIcon={app}\QuantumChess.exe
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

[Icons]
Name: "{autoprograms}\Quantum Chess"; Filename: "{app}\QuantumChess.exe"
Name: "{autodesktop}\Quantum Chess"; Filename: "{app}\QuantumChess.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\QuantumChess.exe"; Description: "{cm:LaunchProgram,Quantum Chess}"; Flags: nowait postinstall skipifsilent
