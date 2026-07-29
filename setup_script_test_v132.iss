; ============================================================
;  SecreAI + RTtranslator 統合インストーラー (v1.3.2 テスト版)
;  Inno Setup 6 スクリプト (テスト環境独立構成)
; ============================================================

#define MyAppName        "SecreAI (Test v1.3.2)"
#define MyAppVersion     "1.3.2-Test"
#define MyAppPublisher   "SecreAI Dev Team"
#define MyAppExeName     "secreAI.exe"

; --- ユーザー指定のソースフォルダ定義 ---
#define SecreAIWPFHub    "D:\SecreAI_Build\SecreAI_Hub.exe"
#define RTTDistDir       "D:\SecreAI_Build\RTtranslator\dist\main.dist"
#define RTTSourceDir     "D:\SecreAI_Build\RTtranslator"

[Setup]
; テスト版専用の独立 AppId
AppId={{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6TEST}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; 本番環境と干渉しない独立インストール先
DefaultDirName={localappdata}\SecreAI_Test_v1.3.2
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=d:\SecreAI_Build\installer_output
OutputBaseFilename=SecreAI_v1.3.2_Test_Setup
SetupIconFile=d:\SecreAI_Build\SecreAI.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english";  MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\python*.dll"
Type: files; Name: "{app}\secreAI.exe"

[Files]
; 1. SecreAI WPFハブ本体
Source: "{#SecreAIWPFHub}"; DestDir: "{app}"; DestName: "secreAI.exe"; Flags: ignoreversion

; 1.2 ポータブルPython環境の同梱
Source: "d:\SecreAI_Build\python_runtime\*"; DestDir: "{app}\python_runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc, __pycache__\*"

; 1.3 Python スクリプト群
Source: "d:\SecreAI_Build\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc, __pycache__\*"

; 1.4 ルート階層の重要 Python スクリプト群
Source: "d:\SecreAI_Build\settings_ui.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\setup_wizard.py"; DestDir: "{app}"; Flags: ignoreversion

; 2. RTtranslator コア
Source: "{#RTTDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json, translation_cache.json, log.json, *.log, debug_rtt.log, data\api_cache\*, data\search_cache\*, paddle\include\*, cupy\*, cupy_backends\*, cupyx\*, scipy\*, scipy.libs\*, pandas\*, pandas.libs\*, matplotlib\*, lxml\*, Cython\*, sklearn\*, skimage\*, shapely\*, shapely.libs\*, docx\*, qt6designer.dll, qt6pdf*.dll, qt6quick3d*.dll, qt6bluetooth.dll, qt6multimedia*.dll, qt6positioning.dll, qt6sensors.dll, qt6nfc.dll, qt6serialport.dll, qt6webchannel.dll, qt6websockets.dll, qt6quickwidgets.dll, qt6texttospeech.dll, qt6spatialaudio.dll"

; 3. 同梱データとドキュメント
Source: "d:\SecreAI_Build\data\lang\*"; DestDir: "{app}\data\lang"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "d:\SecreAI_Build\更新履歴.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\ReadMe.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\SecreAI.ico"; DestDir: "{app}"; Flags: ignoreversion

; 4. RTtranslator 追加データファイル
Source: "{#RTTSourceDir}\models\lid.176.ftz";              DestDir: "{app}\models"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\overlay.html";                    DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\data\wordlists\*";                DestDir: "{app}\data\wordlists"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
