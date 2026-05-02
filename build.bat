@echo off
echo ========================================
echo  SecreAI v1.1.0 - Nuitka Build Script
echo ========================================
echo.
echo ビルドを開始します。完了まで時間がかかります...
echo.

python -m nuitka --standalone --enable-plugin=tk-inter --jobs=12 -o secreAI.exe --include-package=google.genai --include-package=google.auth --include-package=openai --include-package=ollama --include-package=tavily --include-package=httpx --include-package=psutil --include-package=scripts --include-package=chromadb --include-package=numpy --include-package=pygame --include-package=pystray --include-package=keyboard --include-package=pygetwindow --include-package=PIL --include-package=onnxruntime --include-package=requests --include-package=flask --include-package=edge_tts --include-package=sounddevice --include-package=customtkinter --include-package=speech_recognition --include-package=websockets --include-package=asyncio --include-package=pydantic --include-package=typing_extensions --include-package=posthog --include-package-data=onnxruntime --include-package-data=chromadb --include-package-data=customtkinter --include-module=settings_ui --include-module=setup_wizard --include-module=scripts.game_ai --include-module=scripts.update_memory --include-module=scripts.db_maintenance --include-module=scripts.intersecting_ai --include-module=scripts.chromadb_pool --include-module=scripts.clear_history --include-module=scripts.fix_history --include-module=scripts.give_feedback --include-module=scripts.api_cache_system --include-module=scripts.memory_viewer --include-module=scripts.config_manager --include-module=scripts.error_handler --include-module=scripts.stop_ai --include-module=scripts.game_ai_audio_improvements --include-module=scripts.optimization_config --include-module=scripts.optimized_task_queue --include-module=PIL._tkinter_finder --include-data-dir=data/lang=data/lang --noinclude-data-files=data/*.json --noinclude-data-files=data/*.png --windows-console-mode=disable --lto=no --mingw64 --assume-yes-for-downloads --remove-output --windows-icon-from-ico=SecreAI.ico --nofollow-import-to=torch main_hub.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ========================================
echo  ビルド完了！  出力: main_hub.dist\secreAI.exe
echo ========================================
echo.
pause
