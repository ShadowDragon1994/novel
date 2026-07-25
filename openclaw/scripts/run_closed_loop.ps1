$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$entrypoint = Join-Path $projectRoot "closed_loop.py"
$logDirectory = Join-Path $projectRoot "logs"
$logPath = Join-Path $logDirectory "closed_loop.service.log"

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
Set-Location -LiteralPath $projectRoot
$env:PYTHONUNBUFFERED = "1"

& $pythonExe $entrypoint --continuous *>> $logPath
exit $LASTEXITCODE
