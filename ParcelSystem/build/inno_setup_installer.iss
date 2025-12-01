; Inno Setup script (ตัวอย่าง)
[Setup]
AppName=ParcelSystem
AppVersion=0.1
DefaultDirName={pf}\ParcelSystem
DefaultGroupName=ParcelSystem
OutputBaseFilename=ParcelSystem_Installer
Compression=lzma
SolidCompression=yes

[Files]
Source: "dist\ParcelServer.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ParcelClient.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Parcel Server"; Filename: "{app}\ParcelServer.exe"
Name: "{group}\Parcel Client"; Filename: "{app}\ParcelClient.exe"
Name: "{commondesktop}\Parcel Client"; Filename: "{app}\ParcelClient.exe"

[Run]
Filename: "{app}\ParcelServer.exe"; Description: "Start Parcel Server"; Flags: nowait postinstall skipifsilent