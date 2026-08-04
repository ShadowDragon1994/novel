$ErrorActionPreference = "Continue"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "closed_loop.py"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "closed_loop.service.log"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location -LiteralPath $projectRoot
$env:PYTHONUNBUFFERED = "1"

while ($true) {
    $startedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$startedAt] starting closed-loop service" | Out-File -FilePath $logPath -Append -Encoding utf8
    & $pythonExe $entrypoint --continuous *>> $logPath
    $exitCode = $LASTEXITCODE
    $stoppedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$stoppedAt] closed-loop service exited with code $exitCode; restarting in 30 seconds" |
        Out-File -FilePath $logPath -Append -Encoding utf8
    Start-Sleep -Seconds 30
}
