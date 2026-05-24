@echo off
title RTtranslator & SecreAI Hub CS Build Script
echo ========================================================
echo  Starting clean build for WPF (C#) Projects...
echo ========================================================
echo.

set MSBUILD_EXE=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe
set CS_OVERLAY_PROJECT=d:\SecreAI_Build\WPF\RTtranslator_CS_Overlay.csproj
set CS_HUB_PROJECT=d:\SecreAI_Build\WPF\SecreAI_Hub.csproj

if not exist "%MSBUILD_EXE%" (
    echo [ERROR] MSBuild.exe not found at: %MSBUILD_EXE%
    pause
    exit /b 1
)

:: Terminate active processes to release file locks
taskkill /F /IM RTtranslator_CS_Overlay.exe >nul 2>&1
taskkill /F /IM SecreAI_Hub.exe >nul 2>&1

echo ========================================================
echo  1. Building RTtranslator CS Overlay...
echo ========================================================
"%MSBUILD_EXE%" "%CS_OVERLAY_PROJECT%" /p:Configuration=Release /p:Platform=AnyCPU /p:FrameworkPathOverride="C:\Windows\Microsoft.NET\Framework64\v4.0.30319" /t:Rebuild
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] RTtranslator CS Overlay Compilation failed.
    pause
    exit /b 1
)

echo ========================================================
echo  2. Building SecreAI Hub...
echo ========================================================
"%MSBUILD_EXE%" "%CS_HUB_PROJECT%" /p:Configuration=Release /p:Platform=AnyCPU /p:FrameworkPathOverride="C:\Windows\Microsoft.NET\Framework64\v4.0.30319" /t:Rebuild
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] SecreAI Hub Compilation failed.
    pause
    exit /b 1
)

echo.
echo Deploying compiled binaries to workspace...
copy /Y "d:\SecreAI_Build\WPF\bin\Release\RTtranslator_CS_Overlay.exe" "d:\SecreAI_Build\RTtranslator_CS_Overlay.exe"
copy /Y "d:\SecreAI_Build\WPF\bin\Release\RTtranslator_CS_Overlay.exe" "d:\SecreAI_Build\RTtranslator\RTtranslator_CS_Overlay.exe"
copy /Y "d:\SecreAI_Build\WPF\bin\Release\SecreAI_Hub.exe" "d:\SecreAI_Build\SecreAI_Hub.exe"

echo.
echo ========================================================
echo  WPF (C#) Build and Deployment Completed Successfully!
echo ========================================================
pause
