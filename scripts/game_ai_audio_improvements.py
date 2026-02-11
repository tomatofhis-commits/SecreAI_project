# ===== game_ai.py の音声再生部分の改善版 =====
# 既存のrun_voicevox_speak関数とrun_edge_tts_speak関数を以下に置き換える

import contextlib
import atexit

# グローバルなクリーンアップハンドラー
_mixer_initialized = False

def ensure_mixer_cleanup():
    """プログラム終了時にmixerを確実にクリーンアップ"""
    global _mixer_initialized
    if _mixer_initialized and pygame.mixer.get_init():
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
            _mixer_initialized = False
        except:
            pass

# プログラム終了時の自動クリーンアップを登録
atexit.register(ensure_mixer_cleanup)

@contextlib.contextmanager
def managed_mixer(config):
    """
    pygame.mixerのコンテキストマネージャー
    使用後に確実にリソースを解放する
    """
    global _mixer_initialized
    target_device = config.get("DEVICE_NAME")
    
    try:
        if not pygame.mixer.get_init():
            try:
                if target_device and target_device != "デフォルト":
                    pygame.mixer.init(frequency=44100, size=-16, channels=1, devicename=target_device)
                else:
                    pygame.mixer.init(frequency=44100, size=-16, channels=1)
                _mixer_initialized = True
            except:
                pygame.mixer.init(frequency=44100, size=-16, channels=1)
                _mixer_initialized = True
        
        yield
        
    finally:
        # 再生が完了するまで待機
        try:
            while pygame.mixer.music.get_busy():
                time.sleep(0.01)
            pygame.mixer.music.unload()
        except:
            pass

def run_voicevox_speak(text, config, root, session_data):
    """改善版: リソース管理を強化したVOICEVOX音声再生"""
    session_id, session_getter, _ = session_data if session_data else (None, None, None)
    
    # 音声データを貯めるキュー(最大2つ分先行生成しておく)
    audio_queue = queue.Queue(maxsize=2)
    sentences = [s.strip() for s in re.split(r'[。\n！？]', text) if s.strip()]
    speaker_id = config.get("SPEAKER_ID", 3)
    speed = config.get("VOICE_SPEED", 1.2)
    
    # --- [内部関数] 音声を生成してキューに入れる ---
    def generator():
        for s in sentences:
            if session_id and session_getter and session_getter() != session_id: 
                break
            try:
                # 1. クエリ作成
                r1 = requests.post(
                    f"http://127.0.0.1:50021/audio_query?text={s}&speaker={speaker_id}", 
                    timeout=10
                ).json()
                r1["speedScale"] = speed
                r1["volumeScale"] = config.get("VOICE_VOLUME", 1.0)
                r1["postPhonemeLength"] = 0.1
                
                # 2. 音声合成
                r2 = requests.post(
                    f"http://127.0.0.1:50021/synthesis?speaker={speaker_id}", 
                    data=json.dumps(r1), 
                    timeout=30
                )
                if r2.status_code == 200:
                    audio_queue.put(r2.content)
            except Exception as e:
                send_log_to_hub(f"音声生成エラー: {e}", is_error=True)
        audio_queue.put(None) # 終了の合図

    # 生成スレッドを開始
    gen_thread = threading.Thread(target=generator, daemon=True)
    gen_thread.start()

    # --- [再生メイン処理] - コンテキストマネージャーでリソース管理 ---
    with speaker_lock, managed_mixer(config):
        wav_dir = os.path.join(root, "data", "wav")
        os.makedirs(wav_dir, exist_ok=True)
        temp_wav_path = os.path.join(wav_dir, "current_speech.wav")

        vol = 1.0  # エンジン側でコントロールするため固定

        while True:
            audio_data = audio_queue.get()  # 生成が終わるまで待機
            if audio_data is None: 
                break  # 全文終了
            
            if session_id and session_getter and session_getter() != session_id:
                pygame.mixer.music.stop()
                break

            with open(temp_wav_path, "wb") as f:
                f.write(audio_data)
            
            pygame.mixer.music.load(temp_wav_path)
            pygame.mixer.music.set_volume(vol)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                if session_id and session_getter and session_getter() != session_id:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.01)

def run_edge_tts_speak(text, lang_code, config, root, session_data):
    """改善版: リソース管理を強化したEdge-TTS音声再生"""
    session_id, session_getter, _ = session_data if session_data else (None, None, None)
    
    voice = EDGE_TTS_VOICES.get(lang_code, "en-US-AriaNeural")
    
    wav_dir = os.path.join(root, "data", "wav")
    os.makedirs(wav_dir, exist_ok=True)
    temp_mp3_path = os.path.join(wav_dir, "edge_tts_speech.mp3")
    
    async def generate_speech():
        """Edge-TTSで音声を生成"""
        vol = config.get("VOICE_VOLUME", 1.0)
        perc = int((vol - 1.0) * 100)
        vol_str = f"{perc:+}%"
        communicate = edge_tts.Communicate(text, voice, volume=vol_str)
        await communicate.save(temp_mp3_path)
    
    try:
        # 非同期で音声ファイルを生成
        asyncio.run(generate_speech())
        
        if session_id and session_getter and session_getter() != session_id:
            return
        
        # コンテキストマネージャーでリソース管理
        with managed_mixer(config):
            vol = 1.0  # エンジン側でコントロールするため固定
            pygame.mixer.music.load(temp_mp3_path)
            pygame.mixer.music.set_volume(vol)
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                if session_id and session_getter and session_getter() != session_id:
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.05)

    except Exception as e:
        send_log_to_hub(f"Edge-TTS Playback Error: {e}", is_error=True)
    finally:
        # 一時ファイルのクリーンアップ
        try:
            if os.path.exists(temp_mp3_path):
                time.sleep(0.1)  # ファイルロック解除を待つ
                os.remove(temp_mp3_path)
        except:
            pass
