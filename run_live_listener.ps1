$ErrorActionPreference = "Stop"

Write-Host "[VoiceInput] Starting live listener..."
Write-Host "[VoiceInput] Press Ctrl+Win to start/stop recording. Press Esc to exit."
Write-Host ""

py main.py --listen-hotkey --backend deepgram
exit $LASTEXITCODE
