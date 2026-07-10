@echo off
title SecreAI Integrated Build Script (C# WPF Single-out)
echo ========================================================
echo  SecreAI v1.3.0 - Integrated Build System
echo ========================================================
echo.

set MSBUILD_EXE=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe
set ISCC_EXE=G:\Program Files (x86)\Inno Setup 6\ISCC.exe

:: 1. Build WPF (C#)
echo ========================================================
echo  1. Building WPF (C#) SecreAI Hub...
echo ========================================================
if not exist "%MSBUILD_EXE%" (
    echo [ERROR] MSBuild.exe not found at: %MSBUILD_EXE%
    pause
    exit /b 1
)

:: Terminate active processes to release file locks
taskkill /F /IM RTtranslator_CS_Overlay.exe >nul 2>&1
taskkill /F /IM SecreAI_Hub.exe >nul 2>&1

"%MSBUILD_EXE%" "d:\SecreAI_Build\WPF\SecreAI_Hub.csproj" /p:Configuration=Release /p:Platform=AnyCPU /p:FrameworkPathOverride="C:\Windows\Microsoft.NET\Framework64\v4.0.30319" /t:Rebuild
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] SecreAI Hub Compilation failed.
    pause
    exit /b 1
)

copy /Y "d:\SecreAI_Build\WPF\bin\Release\SecreAI_Hub.exe" "d:\SecreAI_Build\SecreAI_Hub.exe"
echo WPF Build Done!


:: 2. Run Inno Setup Compiler
echo ========================================================
echo  3. Building Installer (Inno Setup)...
echo ========================================================
if not exist "%ISCC_EXE%" goto skip_installer

"%ISCC_EXE%" "d:\SecreAI_Build\setup_script.iss"
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Installer build failed.
    pause
    exit /b 1
)
goto build_success

:skip_installer
echo [WARNING] ISCC.exe not found at: %ISCC_EXE%
echo Skipping installer build. Files are compiled in workspace.
pause
exit /b 0

:build_success
echo.
echo ========================================================
echo  Integrated Build Completed Successfully!
echo ========================================================
pause
