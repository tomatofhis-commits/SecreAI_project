@echo off
title SecreAI Zombie Process Cleanup
echo ========================================================
echo  Terminating old background processes...
echo ========================================================
echo.

taskkill /F /IM RTtranslator_core.exe /T
taskkill /F /IM RTtranslator_CS_Overlay.exe /T
taskkill /F /IM SecreAI_Hub.exe /T
taskkill /F /IM python.exe /T

echo.
echo ========================================================
echo  Cleanup Complete!
echo ========================================================
pause
