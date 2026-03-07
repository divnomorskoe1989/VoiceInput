@echo off
setlocal

cd /d "%~dp0"
echo [VoiceInput] Running manual test flow...

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_manual_test.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [VoiceInput] Manual test failed with exit code %EXIT_CODE%.
  if not "%NO_PAUSE%"=="1" pause
  exit /b %EXIT_CODE%
)

echo.
echo [VoiceInput] Manual test completed successfully.
if "%SKIP_LIVE%"=="1" (
  echo [VoiceInput] SKIP_LIVE=1 detected. Live listener is not started.
  echo [VoiceInput] To run E2E manually: run_live_listener.bat
  if not "%NO_PAUSE%"=="1" pause
  exit /b 0
)

echo [VoiceInput] Starting live listener automatically...
call "%~dp0run_live_listener.bat"
set "LIVE_EXIT_CODE=%ERRORLEVEL%"
exit /b %LIVE_EXIT_CODE%
