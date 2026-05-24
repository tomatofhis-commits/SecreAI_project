@echo off
title SecreAI Hub [Development Mode]
cd /d "d:\SecreAI_Build"

set PYTHON_EXE=C:\Users\amach\AppData\Local\Programs\Python\Python312\python.exe

if not exist "%PYTHON_EXE%" (
    set PYTHON_EXE=python
)

"%PYTHON_EXE%" main_hub.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo ========================================================
    echo  [ERROR] Failed to start SecreAI Hub.
    echo ========================================================
    pause
)
