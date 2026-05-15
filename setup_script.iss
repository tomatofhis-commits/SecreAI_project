; ============================================================
;  SecreAI + RTtranslator 統合インストーラー (v1.1.4)
;  Inno Setup 6 スクリプト
; ============================================================

#define MyAppName        "SecreAI"
#define MyAppVersion     "1.1.4"
#define MyAppPublisher   "SecreAI Dev Team"
#define MyAppExeName     "secreAI.exe"

; --- ユーザー指定のソースフォルダ定義 ---
#define SecreAIDistDir   "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\SecreAI_ver1.1.4"
#define RTTDistDir       "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\RTtranslator_ver1.1.4"
#define RTTSourceDir     "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\RTtranslator_ver1.1.4"

[Setup]
AppId={{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=d:\SecreAI_Build\installer_output
OutputBaseFilename=SecreAI_v{#MyAppVersion}_Setup
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

[Files]
; 1. SecreAI 本体（ビルド成果物一式をコピー。config系は除外）
Source: "{#SecreAIDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config\config.json, data\config.json, data\rtt_config.json, data\chat_history.json, memory_db\*"

; 2. RTtranslator コア（ビルド成果物一式をコピー。キャッシュ系は除外）
Source: "{#RTTDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json, translation_cache.json, log.json, debug_rtt.log"

; 3. RTtranslator 追加データファイル（distに含まれていない場合のみ個別にコピーされるよう skipifsourcedoesntexist を維持）
; ※通常はビルド成果物のフォルダ内に含まれているため、予備的な記述です。
Source: "{#RTTSourceDir}\models\lid.176.ftz";              DestDir: "{app}\models"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\frozen_east_text_detection.pb";   DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\overlay.html";                    DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\data\wordlists\*";                DestDir: "{app}\data\wordlists"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
