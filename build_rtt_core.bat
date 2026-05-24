@echo off
title RTtranslator Python Core Build Script
echo ========================================================
echo  Starting Nuitka compilation for Python Core...
echo ========================================================
echo.

cd /d "d:\SecreAI_Build\RTtranslator"
call build.bat

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Nuitka compilation failed. Please check errors above.
    pause
    exit /b 1
)

echo.
echo ========================================================
echo  Python Core Build and Deployment Completed Successfully!
echo ========================================================
pause
