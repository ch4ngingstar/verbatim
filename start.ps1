# Start both Verbatim services in separate terminal windows.
# Run from the repo root: .\start.ps1

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$repo'; python -m uvicorn verbatim.api.app:app --port 8000 --reload" `
  -WorkingDirectory "$repo\src"

Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$repo\ui'; npm run dev" `
  -WorkingDirectory "$repo\ui"

Write-Host "Backend : http://localhost:8000/api/health"
Write-Host "Frontend: http://localhost:3000"
