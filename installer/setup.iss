; LOF基金数据服务 - Windows 安装包脚本
; 使用 Inno Setup 6 编译

[Setup]
AppId={{8A2D5F3E-9B1C-4D7A-8E6F-3C2B1A5D9E7F}
AppName=LOF基金数据服务
AppVersion=1.0.0
AppPublisher=LOF基金项目组
AppPublisherURL=https://github.com/woredasdnmv/get-lof-test
AppSupportURL=https://github.com/woredasdnmv/get-lof-test/issues
DefaultDirName={autopf}\LOF基金服务
DefaultGroupName=LOF基金数据服务
AllowNoIcons=yes
; 输出配置
OutputDir=installer\output
OutputBaseFilename=LOF基金服务_Setup_v1.0.0
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
; 权限
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
; 界面
SetupWindowTitle=LOF基金数据服务 安装向导
UninstallDisplayIcon={app}\LOF基金服务.exe
UninstallDisplayName=LOF基金数据服务
; 许可协议（可选）
; LicenseFile=LICENSE.txt
; 信息
InfoBeforeFile=installer\安装说明.txt
InfoAfterFile=installer\使用说明.txt

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1; Check: not Is64BitInstallMode

[Files]
; 后端服务可执行文件
Source: "dist\LOF基金服务.exe"; DestDir: "{app}"; Flags: ignoreversion
; 前端静态文件
Source: "index.html"; DestDir: "{app}\web"; Flags: ignoreversion
Source: "css\*"; DestDir: "{app}\web\css"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "js\*"; DestDir: "{app}\web\js"; Flags: ignoreversion recursesubdirs createallsubdirs
; 配置文件
Source: "config.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "sz_lof_codes.json"; DestDir: "{app}"; Flags: ignoreversion
; 启动脚本
Source: "installer\启动服务.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer\停止服务.bat"; DestDir: "{app}"; Flags: ignoreversion
; 文档
Source: "README.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "API文档-前端对接.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "API文档-微信小程序对接.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\启动服务"; Filename: "{app}\启动服务.bat"; WorkingDir: "{app}"
Name: "{group}\打开前端页面"; Filename: "{app}\web\index.html"; WorkingDir: "{app}\web"
Name: "{group}\停止服务"; Filename: "{app}\停止服务.bat"; WorkingDir: "{app}"
Name: "{group}\卸载"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LOF基金服务"; Filename: "{app}\启动服务.bat"; Tasks: desktopicon

[Run]
Filename: "{app}\启动服务.bat"; Description: "立即启动服务"; Flags: nowait postinstall skipifsilent

[Registry]
; 添加到防火墙规则（需要管理员权限）
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"; ValueType: string; ValueName: "LOFService_IN"; ValueData: "v2.30|Action=Allow|Active=TRUE|Dir=In|Protocol=TCP|LPort=5000|App={app}\LOF基金服务.exe|Name=LOF基金服务 - 入站|Desc=允许访问LOF基金服务API"; Flags: createvalueifdoesntexist
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules"; ValueType: string; ValueName: "LOFService_OUT"; ValueData: "v2.30|Action=Allow|Active=TRUE|Dir=Out|Protocol=TCP|App={app}\LOF基金服务.exe|Name=LOF基金服务 - 出站|Desc=允许LOF基金服务访问网络"; Flags: createvalueifdoesntexist

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // 安装完成后可选操作
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    // 卸载后清理防火墙规则
    RegDeleteValue(HKLM, 'SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules', 'LOFService_IN');
    RegDeleteValue(HKLM, 'SYSTEM\CurrentControlSet\Services\SharedAccess\Parameters\FirewallPolicy\FirewallRules', 'LOFService_OUT');
  end;
end;
