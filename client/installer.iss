; TalkFlow Windows Installer Script
; ==================================
; Inno Setup script for creating a Windows installer package.
;
; Requirements:
;   - Inno Setup 6.x (https://jrsoftware.org/isinfo.php)
;   - TalkFlow.exe built by build_installer.py (in dist/ folder)
;
; Usage:
;   1. Build the executable: python build_installer.py
;   2. Compile this script with Inno Setup Compiler
;   3. Output: TalkFlow-Setup-{version}.exe

#define MyAppName "TalkFlow"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "AI Implemented"
#define MyAppURL "https://github.com/ai-implemented/talkflow"
#define MyAppExeName "TalkFlow.exe"
#define MyAppDescription "Push-to-talk voice dictation"

[Setup]
; App identification
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Installation directories
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; Output settings
OutputDir=installer_output
OutputBaseFilename=TalkFlow-Setup-{#MyAppVersion}
SetupIconFile=assets\logo.ico

; Compression
Compression=lzma2/ultra64
SolidCompression=yes

; Windows version requirements (Windows 10+)
MinVersion=10.0

; Privileges - install for current user by default, with option for all users
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Appearance
WizardStyle=modern
WizardSizePercent=100

; Uninstall info
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; License (optional - uncomment and create LICENSE.txt if needed)
; LicenseFile=LICENSE.txt

; Info before/after install (optional)
; InfoBeforeFile=README.txt
; InfoAfterFile=CHANGELOG.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Start TalkFlow when Windows starts"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; Main executable
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Assets folder (icon, etc.)
Source: "assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs

; Config file template (optional)
; Source: "config.json.template"; DestDir: "{app}"; DestName: "config.json"; Flags: onlyifdoesntexist

[Icons]
; Start Menu shortcut
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "{#MyAppDescription}"

; Desktop shortcut (optional task)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "{#MyAppDescription}"

[Registry]
; Register in Windows startup (optional task)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: startupicon; Flags: uninsdeletevalue

; Application settings (for future use)
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\{#MyAppPublisher}\{#MyAppName}"; ValueType: string; ValueName: "Version"; ValueData: "{#MyAppVersion}"; Flags: uninsdeletekey

[Run]
; Option to launch app after installation
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Clean shutdown before uninstall (optional)
; Filename: "{app}\{#MyAppExeName}"; Parameters: "--quit"; Flags: skipifdoesntexist runhidden

[UninstallDelete]
; Clean up config and logs on uninstall
Type: filesandordirs; Name: "{app}\config.json"
Type: filesandordirs; Name: "{app}\*.log"
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Pascal Script for custom installation logic

function InitializeSetup(): Boolean;
begin
  Result := True;
  // Add any pre-installation checks here
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    // Post-installation tasks
    // For example, create default config file
  end;
end;

function InitializeUninstall(): Boolean;
var
  AppRunning: Boolean;
  ResultCode: Integer;
begin
  Result := True;

  // Check if the application is running
  AppRunning := False;
  if FileExists(ExpandConstant('{app}\{#MyAppExeName}')) then
  begin
    // Try to detect if process is running (simplified check)
    // In production, use a more robust method
  end;

  if AppRunning then
  begin
    if MsgBox('TalkFlow is currently running. Close it before uninstalling?',
              mbConfirmation, MB_YESNO) = IDYES then
    begin
      // Attempt to close the application gracefully
      // ShellExec('open', ExpandConstant('{app}\{#MyAppExeName}'), '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;

[Messages]
; Custom messages
BeveledLabel=TalkFlow - Voice Dictation for Windows

[CustomMessages]
; Localized strings
english.LaunchAfterInstall=Launch TalkFlow after installation
