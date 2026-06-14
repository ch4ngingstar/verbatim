# Start both Verbatim services in separate terminal windows.
# Run from the repo root: .\start.ps1

$repo = Split-Path -Parent $MyInvocation.MyCommand.Path

# First-run: create .env files if missing
if (-not (Test-Path "$repo\.env")) {
    Copy-Item "$repo\.env.example" "$repo\.env"
    Write-Host "Created .env from .env.example"
}
if (-not (Test-Path "$repo\ui\.env.local")) {
    "NEXT_PUBLIC_API_URL=http://localhost:8000" | Out-File "$repo\ui\.env.local" -Encoding utf8
    Write-Host "Created ui/.env.local"
}

# First-run: create data directory
if (-not (Test-Path "$repo\data")) {
    New-Item -ItemType Directory "$repo\data" | Out-Null
    Write-Host "Created data/ directory"
}

# Start backend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$repo\src'; python -m uvicorn verbatim.api.app:app --port 8000 --reload"

# Start frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "Set-Location '$repo\ui'; npm run dev"

Write-Host ""
Write-Host "Starting Verbatim..."
Write-Host "  Backend : http://localhost:8000/api/health"
Write-Host "  Frontend: http://localhost:3000"
Write-Host ""

# Open browser after a short delay
Start-Sleep -Seconds 4
Start-Process "http://localhost:3000"
