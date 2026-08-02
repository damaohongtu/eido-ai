#define MyVersion GetEnv("EIDO_INSTALLER_VERSION")
#define MySourceRoot GetEnv("EIDO_INSTALLER_SOURCE")
#define MyOutputDir GetEnv("EIDO_INSTALLER_OUTPUT")
#define MyOutputBaseName GetEnv("EIDO_INSTALLER_OUTPUT_BASENAME")

[Setup]
AppId={{AE2E3D89-39EA-41A2-8A6A-3F3B3C89B834}
AppName=Eido OpenCode Launcher
AppVersion={#MyVersion}
AppPublisher=Eido
DefaultDirName={localappdata}\Eido
DisableProgramGroupPage=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyOutputBaseName}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName=Eido OpenCode Launcher
UninstallDisplayIcon={app}\bin\eido-opencode-launcher.exe
WizardStyle=modern
MinVersion=10.0
CloseApplications=no

[Files]
Source: "{#MySourceRoot}\bin\eido-opencode-launcher.exe"; DestDir: "{app}\bin"; Flags: ignoreversion
Source: "{#MySourceRoot}\ai.eido.opencode_launcher.json"; DestDir: "{app}"; Flags: ignoreversion

[Registry]
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher"; ValueType: string; ValueName: ""; ValueData: "{app}\ai.eido.opencode_launcher.json"; Flags: uninsdeletekey

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ManifestPath: String;
  ManifestLines: TArrayOfString;
  LauncherPath: String;
  LineIndex: Integer;
begin
  if CurStep <> ssPostInstall then
    Exit;

  ManifestPath := ExpandConstant('{app}\ai.eido.opencode_launcher.json');
  if not LoadStringsFromFile(ManifestPath, ManifestLines) then
    RaiseException('Could not read the Native Messaging manifest.');

  LauncherPath := ExpandConstant('{app}\bin\eido-opencode-launcher.exe');
  StringChangeEx(LauncherPath, '\', '\\', True);
  for LineIndex := 0 to GetArrayLength(ManifestLines) - 1 do
    StringChangeEx(ManifestLines[LineIndex], '__EIDO_LAUNCHER_PATH__', LauncherPath, True);

  if not SaveStringsToUTF8FileWithoutBOM(ManifestPath, ManifestLines, False) then
    RaiseException('Could not write the Native Messaging manifest.');
end;
