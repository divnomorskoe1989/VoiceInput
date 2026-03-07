$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-Host ""
    Write-Host "[$Label]"
    & $Action
}

Invoke-Step "1/6 Baseline run" {
    py main.py
    if ($LASTEXITCODE -ne 0) { throw "Baseline run failed: exit code $LASTEXITCODE" }
}

Invoke-Step "2/6 Mock smoke" {
    py main.py --once --backend mock --simulate-text "manual mock check"
    if ($LASTEXITCODE -ne 0) { throw "Mock smoke failed: exit code $LASTEXITCODE" }
}

Invoke-Step "3/6 Deepgram key validation" {
    py -c "import sys; from stt_client import DeepgramSTTClient;`ntry:`n    DeepgramSTTClient(api_key='').connect()`nexcept ValueError:`n    print('deepgram_key_validation_ok'); sys.exit(0)`nprint('unexpected_success'); sys.exit(1)"
    if ($LASTEXITCODE -ne 0) { throw "Deepgram key validation failed: exit code $LASTEXITCODE" }
}

Invoke-Step "4/6 Runtime deps check" {
    py -c "import websockets, sounddevice, numpy, pynput; print('deps_ok')"
    if ($LASTEXITCODE -ne 0) { throw "Dependency check failed: exit code $LASTEXITCODE" }
}

Invoke-Step "5/6 Quality report" {
    py quality_report.py --log tmp/voice_input_recovered.log --output tmp/quality_report.json
    if ($LASTEXITCODE -ne 0) { throw "quality_report failed: exit code $LASTEXITCODE" }
    Get-Content tmp/quality_report.json
}

Invoke-Step "6/6 Live mode hint" {
    Write-Host "Run live mode:"
    Write-Host "  run_live_listener.bat"
    Write-Host "or"
    Write-Host "  py main.py --listen-hotkey --backend deepgram"
    Write-Host "Press Ctrl+Win to start/stop. Auto-stop triggers after 5s of silence."
}
