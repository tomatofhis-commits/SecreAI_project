; ============================================================
;  SecreAI + RTtranslator 統合インストーラー
;  Inno Setup 6 スクリプト
; ============================================================

#define MyAppName        "SecreAI"
#define MyAppVersion     "1.1.1"
#define MyAppPublisher   "SecreAI Dev Team"
#define MyAppExeName     "secreAI.exe"

; --- ソースフォルダ定義 ---
; SecreAI のビルド成果物フォルダ（整理済み）
#define SecreAIDistDir   "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\SecreAI_ver1.1.1"
#define RTTDistDir       "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\RTtranslator_ver1.0.1"
#define RTTSourceDir     "C:\Users\amach\OneDrive\デスクトップ\アップ用作業\RTtranslator_ver1.0.1"

[Setup]
AppId={{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=C:\Users\amach\OneDrive\デスクトップ\アップ用作業
OutputBaseFilename=SecreAI_v{#MyAppVersion}_Setup
SetupIconFile=d:\SecreAI_Build\SecreAI.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
; 既存アプリを安全に上書きアップグレード
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english";  MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; ============================================================
; 1. SecreAI 本体（Nuitkaビルド成果物）
; ============================================================
Source: "{#SecreAIDistDir}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SecreAIDistDir}\*";               DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config\config.json, data\config.json, data\rtt_config.json, data\chat_history.json, memory_db\*"

; ============================================================
; 2. RTtranslator コア（Nuitkaビルド成果物）
;    main.dist フォルダの全ファイルを SecreAI と同じ {app} に同居
; ============================================================
Source: "{#RTTDistDir}\RTtranslator_core.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RTTDistDir}\*";                     DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json, translation_cache.json, log.json"

; ============================================================
; 3. RTtranslator 追加データファイル
;    （Nuitkaに --include-data-file で含まれない場合のフォールバック）
; ============================================================
; fastText 言語判定モデル
Source: "{#RTTSourceDir}\models\lid.176.ftz";              DestDir: "{app}\models"; Flags: ignoreversion skipifsourcedoesntexist
; EAST テキスト検出モデル（存在する場合のみ）
Source: "{#RTTSourceDir}\frozen_east_text_detection.pb";   DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
; オーバーレイHTML
Source: "{#RTTSourceDir}\overlay.html";                    DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
; ワードリスト辞書
Source: "{#RTTSourceDir}\data\wordlists\*";                DestDir: "{app}\data\wordlists"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
