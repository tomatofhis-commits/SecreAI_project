; ============================================================
;  SecreAI + RTtranslator 統合インストーラー (v1.3.0)
;  Inno Setup 6 スクリプト
; ============================================================

#define MyAppName        "SecreAI"
#define MyAppVersion     "1.3.0"
#define MyAppPublisher   "SecreAI Dev Team"
#define MyAppExeName     "secreAI.exe"

; --- ユーザー指定のソースフォルダ定義 ---
#define SecreAIWPFHub    "D:\SecreAI_Build\SecreAI_Hub.exe"
#define RTTDistDir       "D:\SecreAI_Build\RTtranslator\dist\main.dist"
#define RTTSourceDir     "D:\SecreAI_Build\RTtranslator"

[Setup]
; デバッグ版用の独立IDを設定
AppId={{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; インストール先をデバッグ専用のSecreAI_Debugフォルダに設定します
DefaultDirName={localappdata}\SecreAI
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

[InstallDelete]
; 古いPython版ハブがルート上に配置していたDLLや.pyd等のファイルをクリーンアップします（データフォルダは保護されます）
Type: files; Name: "{app}\*.pyd"
Type: files; Name: "{app}\*.dll"
Type: files; Name: "{app}\python*.dll"
Type: files; Name: "{app}\secreAI.exe"

[Files]
; ==============================================================================
;  【厳格な除外ルール】インストーラー制作時に不要ファイルを混入させないための規定
;  1. 設定ファイル (config.json, rtt_config.json 等) はユーザー毎に初期化されるべきため同梱禁止。
;  2. 個人データ・会話データベース (chat_history.json, memory_db\* 等) はプライバシーと初期化のため同梱禁止。
;  3. キャッシュ (api_cache\*, search_cache\*, wav\* 音声合成キャッシュ等) は配布サイズ削減のため同梱禁止。
;  4. 各種ログファイル (*.log) やキャプチャ中の一時画像 (temp_ss.png, temp_query_image.png) は同梱禁止。
; ==============================================================================

; 1. SecreAI WPFハブ本体（ビルドされた SecreAI_Hub.exe を secreAI.exe としてメインパスへコピー）
Source: "{#SecreAIWPFHub}"; DestDir: "{app}"; DestName: "secreAI.exe"; Flags: ignoreversion

; 1.2 ポータブルPython環境の同梱
Source: "d:\SecreAI_Build\python_runtime\*"; DestDir: "{app}\python_runtime"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc, __pycache__\*"

; 1.3 Python スクリプト群（ハブから起動される game_ai.py 等のスクリプトとライブラリ、不要なキャッシュ・一時データを除外）
Source: "d:\SecreAI_Build\scripts\*"; DestDir: "{app}\scripts"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc, __pycache__\*"

; 1.4 ルート階層の重要 Python スクリプト群の同梱 (設定画面・ウィザード起動用)
Source: "d:\SecreAI_Build\settings_ui.py";  DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\setup_wizard.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\update_lang.py";  DestDir: "{app}"; Flags: ignoreversion

; 2. RTtranslator コア（本体と重複する巨大ライブラリ、および設定・ログ・キャッシュを除外）
Source: "{#RTTDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.json, translation_cache.json, log.json, *.log, debug_rtt.log, data\api_cache\*, data\search_cache\*, paddle\include\*, cupy\*, cupy_backends\*, cupyx\*, scipy\*, scipy.libs\*, pandas\*, pandas.libs\*, matplotlib\*, lxml\*, Cython\*, sklearn\*, skimage\*, shapely\*, shapely.libs\*, docx\*, qt6designer.dll, qt6pdf*.dll, qt6quick3d*.dll, qt6bluetooth.dll, qt6multimedia*.dll, qt6positioning.dll, qt6sensors.dll, qt6nfc.dll, qt6serialport.dll, qt6webchannel.dll, qt6websockets.dll, qt6quickwidgets.dll, qt6texttospeech.dll, qt6spatialaudio.dll"

; 3. 同梱漏れしていた追加データとドキュメント
Source: "d:\SecreAI_Build\data\lang\*"; DestDir: "{app}\data\lang"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "d:\SecreAI_Build\更新履歴.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\ReadMe.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "d:\SecreAI_Build\SecreAI.ico"; DestDir: "{app}"; Flags: ignoreversion

; 4. RTtranslator 追加データファイル（distに含まれていない場合のみ個別にコピーされるよう skipifsourcedoesntexist を維持）
Source: "{#RTTSourceDir}\models\lid.176.ftz";              DestDir: "{app}\models"; Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\overlay.html";                    DestDir: "{app}";        Flags: ignoreversion skipifsourcedoesntexist
Source: "{#RTTSourceDir}\data\wordlists\*";                DestDir: "{app}\data\wordlists"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// レジストリから旧バージョンのインストールフォルダパスを取得する関数
function GetInstalledPath(AppId: String): String;
var
  RegKey: String;
  Path: String;
begin
  Result := '';
  RegKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\' + AppId + '_is1';
  // HKEY_CURRENT_USER (lowest privilege でのインストールを優先チェック)
  if RegQueryStringValue(HKCU, RegKey, 'Inno Setup: App Path', Path) then
  begin
    Result := Path;
    Exit;
  end;
  // HKEY_LOCAL_MACHINE (管理者権限でのインストールもチェック)
  if RegQueryStringValue(HKLM, RegKey, 'Inno Setup: App Path', Path) then
  begin
    Result := Path;
    Exit;
  end;
end;

// ファイルおよびフォルダのコピー処理（Langフォルダは除外）
procedure CopyUserFiles(SrcDir, DestDir: String);
var
  SrcFile, DestFile: String;
  SrcDbDir, DestDbDir: String;
  FindRec: TFindRec;
begin
  // コピー元とコピー先が同じであるか、または空パスの場合は処理しない
  if (SrcDir = '') or (CompareText(SrcDir, DestDir) = 0) then Exit;
  if not DirExists(SrcDir) then Exit;

  // data フォルダを作成
  ForceDirectories(AddBackslash(DestDir) + 'data');

  // 1. data\config.json
  SrcFile := AddBackslash(SrcDir) + 'data\config.json';
  DestFile := AddBackslash(DestDir) + 'data\config.json';
  if FileExists(SrcFile) and (not FileExists(DestFile)) then
  begin
    CopyFile(SrcFile, DestFile, False);
  end;

  // 2. data\rtt_config.json
  SrcFile := AddBackslash(SrcDir) + 'data\rtt_config.json';
  DestFile := AddBackslash(DestDir) + 'data\rtt_config.json';
  if FileExists(SrcFile) and (not FileExists(DestFile)) then
  begin
    CopyFile(SrcFile, DestFile, False);
  end;

  // 3. data\chat_history.json
  SrcFile := AddBackslash(SrcDir) + 'data\chat_history.json';
  DestFile := AddBackslash(DestDir) + 'data\chat_history.json';
  if FileExists(SrcFile) and (not FileExists(DestFile)) then
  begin
    CopyFile(SrcFile, DestFile, False);
  end;

  // 4. data\feedback_memory.json
  SrcFile := AddBackslash(SrcDir) + 'data\feedback_memory.json';
  DestFile := AddBackslash(DestDir) + 'data\feedback_memory.json';
  if FileExists(SrcFile) and (not FileExists(DestFile)) then
  begin
    CopyFile(SrcFile, DestFile, False);
  end;

  // 5. memory_db フォルダの移行
  SrcDbDir := AddBackslash(SrcDir) + 'memory_db';
  DestDbDir := AddBackslash(DestDir) + 'memory_db';
  if DirExists(SrcDbDir) and (not DirExists(DestDbDir)) then
  begin
    ForceDirectories(DestDbDir);
    // フォルダ内のファイルをコピー
    if FindFirst(SrcDbDir + '\*', FindRec) then
    begin
      try
        repeat
          if (FindRec.Name <> '.') and (FindRec.Name <> '..') then
          begin
            if (FindRec.Attributes and FILE_ATTRIBUTE_DIRECTORY) = 0 then
            begin
              CopyFile(SrcDbDir + '\' + FindRec.Name, DestDbDir + '\' + FindRec.Name, False);
            end;
          end;
        until not FindNext(FindRec);
      finally
        FindClose(FindRec);
      end;
    end;
  end;
end;

// インストール完了ステップでのフック処理
procedure CurStepChanged(CurStep: TSetupStep);
var
  OldPath: String;
  NewPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    NewPath := ExpandConstant('{app}');
    // 旧通常版の AppId: {C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H} から移行
    OldPath := GetInstalledPath('{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H}');
    if OldPath <> '' then
    begin
      CopyUserFiles(OldPath, NewPath);
    end;
  end;
end;
