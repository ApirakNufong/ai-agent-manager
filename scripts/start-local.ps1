param([string]$Python = 'python', [string]$MqttPassword, [string]$ApiToken = '')
$ErrorActionPreference = 'Stop'
if (-not $MqttPassword) { throw 'Supply -MqttPassword to authenticate to Mosca.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:MQTT_PASSWORD = $MqttPassword
$env:API_TOKEN = $ApiToken
$env:MQTT_HOST = '127.0.0.1'
$processes = @()
try {
    Push-Location (Join-Path $projectRoot 'backend')
    & $Python -m app.seed
    if ($LASTEXITCODE -ne 0) { throw 'Backend initialization failed' }
    Pop-Location
    $processes += Start-Process node -ArgumentList 'server.js' -WorkingDirectory (Join-Path $projectRoot 'mosca') -WindowStyle Hidden -PassThru
    $processes += Start-Process $Python -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru
    foreach ($identity in @('engine','manager','BOT-001','BOT-002','BOT-003')) {
        $processes += Start-Process $Python -ArgumentList '-m','app.runtime',$identity -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -PassThru
    }
    Write-Host 'Services started. In another terminal run npm run dev from frontend. Press Enter to stop these services.'
    Read-Host | Out-Null
} finally {
    foreach ($process in $processes) { if (-not $process.HasExited) { Stop-Process -Id $process.Id -ErrorAction SilentlyContinue } }
}
