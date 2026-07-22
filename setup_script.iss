; ============================================================
;  SecreAI + RTtranslator 統合インストーラー (v1.3.1)
;  Inno Setup 6 スクリプト
; ============================================================

#define MyAppName        "SecreAI"
#define MyAppVersion     "1.3.1"
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

// 古い競合フォルダのクリーンアップ処理（保護フォルダ data, memory_db, models は絶対に除外）
procedure CleanOldConflictDirs(AppDir: String);
var
  TargetDirs: array[0..74] of String;
  I: Integer;
  Path: String;
begin
  if AppDir = '' then Exit;
  
  // 以前の古いPython環境でルート直下にインストールされていた、不要かつ新しいポータブル環境と衝突するライブラリフォルダの一覧
  TargetDirs[0] := 'Cython';
  TargetDirs[1] := 'PIL';
  TargetDirs[2] := 'PyQt6';
  TargetDirs[3] := 'PySide6';
  TargetDirs[4] := '_sounddevice_data';
  TargetDirs[5] := '_websocket';
  TargetDirs[6] := 'aiohttp';
  TargetDirs[7] := 'astor';
  TargetDirs[8] := 'av';
  TargetDirs[9] := 'av.libs';
  TargetDirs[10] := 'bcrypt';
  TargetDirs[11] := 'brotlicffi_bak';
  TargetDirs[12] := 'certifi';
  TargetDirs[13] := 'chardet';
  TargetDirs[14] := 'charset_normalizer';
  TargetDirs[15] := 'chromadb';
  TargetDirs[16] := 'chromadb_rust_bindings';
  TargetDirs[17] := 'contourpy';
  TargetDirs[18] := 'cryptography';
  TargetDirs[19] := 'ctranslate2';
  TargetDirs[20] := 'cupy';
  TargetDirs[21] := 'cupy_backends';
  TargetDirs[22] := 'cupyx';
  TargetDirs[23] := 'customtkinter';
  TargetDirs[24] := 'cv2';
  TargetDirs[25] := 'docx';
  TargetDirs[26] := 'dxcam';
  TargetDirs[27] := 'frozenlist';
  TargetDirs[28] := 'google';
  TargetDirs[29] := 'grpc';
  TargetDirs[30] := 'hf_xet';
  TargetDirs[31] := 'httptools';
  TargetDirs[32] := 'jaraco';
  TargetDirs[33] := 'jiter';
  TargetDirs[34] := 'jsonschema_specifications';
  TargetDirs[35] := 'kiwisolver';
  TargetDirs[36] := 'lmdb';
  TargetDirs[37] := 'lxml';
  TargetDirs[38] := 'markupsafe';
  TargetDirs[39] := 'matplotlib';
  TargetDirs[40] := 'multidict';
  TargetDirs[41] := 'numpy';
  TargetDirs[42] := 'numpy.libs';
  TargetDirs[43] := 'pandas';
  TargetDirs[44] := 'pandas.libs';
  TargetDirs[45] := 'propcache';
  TargetDirs[46] := 'psutil';
  TargetDirs[47] := 'pyaudio';
  TargetDirs[48] := 'pybase64';
  TargetDirs[49] := 'pyclipper';
  TargetDirs[50] := 'pydantic_core';
  TargetDirs[51] := 'pygame';
  TargetDirs[52] := 'rapidfuzz';
  TargetDirs[53] := 'regex';
  TargetDirs[54] := 'rpds';
  TargetDirs[55] := 'scipy';
  TargetDirs[56] := 'scipy.libs';
  TargetDirs[57] := 'shapely';
  TargetDirs[58] := 'shapely.libs';
  TargetDirs[59] := 'shiboken6';
  TargetDirs[60] := 'skimage';
  TargetDirs[61] := 'sklearn';
  TargetDirs[62] := 'speech_recognition';
  TargetDirs[63] := 'tcl';
  TargetDirs[64] := 'tcl8';
  TargetDirs[65] := 'tiktoken';
  TargetDirs[66] := 'tk';
  TargetDirs[67] := 'tokenizers';
  TargetDirs[68] := 'tzdata';
  TargetDirs[69] := 'watchfiles';
  TargetDirs[70] := 'websockets';
  TargetDirs[71] := 'winrt';
  TargetDirs[72] := 'yaml';
  TargetDirs[73] := 'yarl';
  TargetDirs[74] := 'zstandard';

  for I := 0 to 74 do
  begin
    Path := AddBackslash(AppDir) + TargetDirs[I];
    if DirExists(Path) then
    begin
      DelTree(Path, True, True, True);
    end;
  end;
end;

// インストール完了ステップでのフック処理
procedure CurStepChanged(CurStep: TSetupStep);
var
  OldPath: String;
  NewPath: String;
begin
  NewPath := ExpandConstant('{app}');

  // ファイル展開直前に古い競合フォルダを自動削除（クリーンアップ）する
  if CurStep = ssInstall then
  begin
    CleanOldConflictDirs(NewPath);
  end;

  if CurStep = ssPostInstall then
  begin
    // 旧通常版の AppId: {C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H} から移行
    OldPath := GetInstalledPath('{C12F4B7A-9E5C-4F3D-8A1B-2C3D4E5F6G7H}');
    if OldPath <> '' then
    begin
      CopyUserFiles(OldPath, NewPath);
    end;
  end;
end;
