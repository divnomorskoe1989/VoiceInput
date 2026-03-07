@echo off
setlocal

cd /d "%~dp0"
echo [VoiceInput] Starting live listener...
echo [VoiceInput] Press Ctrl+Win to start/stop recording. Press Esc to exit.
echo.

py main.py --listen-hotkey --backend deepgram
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [VoiceInput] Listener stopped with exit code %EXIT_CODE%.
if not "%NO_PAUSE%"=="1" pause
exit /b %EXIT_CODE%
