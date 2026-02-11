@echo off
taskkill /f /im ollama.exe >nul 2>&1
timeout /t 2 /nobreak
set CUDA_VISIBLE_DEVICES=GPU-bf332029-a056-f265-7930-3cfecf2ac71e,GPU-9fe1036e-2000-3b5f-e356-2eec3a7129f9
set OLLAMA_SCHED_SPREAD=1
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
exit