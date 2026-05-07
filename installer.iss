; installer.iss - Inno Setup 安装包配置
[Setup]
AppName=ClipLingo
AppVersion=1.0
AppPublisher=ClipLingo
DefaultDirName={autopf}\ClipLingo
DefaultGroupName=ClipLingo
OutputBaseFilename=ClipLingo_Setup
OutputDir=dist
Compression=lzma2/ultra64
SolidCompression=yes
; 要求管理员权限（写入 Program Files 需要）
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=frontend\public\favicon.ico
DisableDirPage=no

[Files]
; 主程序（PyInstaller 打包产物，含 ffmpeg + faster-whisper）
Source: "dist\ClipLingo\*"; DestDir: "{app}"; Flags: recursesubdirs

[Icons]
Name: "{group}\ClipLingo"; Filename: "{app}\ClipLingo.exe"; IconFilename: "{app}\ClipLingo.exe"
Name: "{userdesktop}\ClipLingo"; Filename: "{app}\ClipLingo.exe"; IconFilename: "{app}\ClipLingo.exe"

[Run]
Filename: "{app}\ClipLingo.exe"; Description: "立即启动"; Flags: postinstall skipifsilent

[UninstallDelete]
; 卸载时清理用户生成的目录
Type: filesandordirs; Name: "{app}\output"
Type: filesandordirs; Name: "{app}\temp"
Type: filesandordirs; Name: "{app}\logs"
