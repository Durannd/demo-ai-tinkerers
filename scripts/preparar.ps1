# Prepara a DEMO. Rode UMA VEZ, EM CASA, COM INTERNET (baixa ~1 GB: node_modules, Chrome do Remotion, modelo whisper).
# Uso (na raiz do repo):  powershell -ExecutionPolicy Bypass -File scripts\preparar.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONUTF8 = "1"

function Passo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Falta($t) { Write-Host "[ERRO] $t" -ForegroundColor Red; exit 1 }

Passo "1/7 Pré-requisitos (python 3.10+, node 18+, ffmpeg)"
$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) { Falta "Python não encontrado. Instale: winget install Python.Python.3.12" }
& python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Falta "Python 3.10+ é necessário." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Falta "Node.js não encontrado. Instale: winget install OpenJS.NodeJS.LTS" }
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Falta "ffmpeg não está no PATH. Instale: winget install Gyan.FFmpeg (e reabra o terminal)" }
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) { Falta "ffprobe não está no PATH (vem junto com o ffmpeg)." }

Passo "2/7 Ambiente Python (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { & python -m venv .venv; if ($LASTEXITCODE -ne 0) { Falta "falha ao criar .venv" } }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Falta "pip install falhou" }

Passo "3/7 Remotion (npm install em render/)"
Push-Location render
& npm install --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Pop-Location; Falta "npm install falhou" }

Passo "4/7 Chrome do Remotion (chrome-headless-shell)"
& npx remotion browser ensure
if ($LASTEXITCODE -ne 0) { Pop-Location; Falta "npx remotion browser ensure falhou" }
Pop-Location

Passo "5/7 Modelo whisper 'small' (~460 MB) em assets\modelos\faster-whisper"
$cod = @'
from faster_whisper import WhisperModel
import pathlib
raiz = pathlib.Path(".").resolve()
WhisperModel("small", device="cpu", compute_type="int8", download_root=str(raiz / "assets" / "modelos" / "faster-whisper"))
print("whisper small ok")
'@
& .venv\Scripts\python.exe -c $cod
if ($LASTEXITCODE -ne 0) { Falta "download do whisper falhou" }

Passo "6/7 .env"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Criei .env. EDITE e coloque GEMINI_API_KEY=... (https://aistudio.google.com/apikey)" -ForegroundColor Yellow }
else { Write-Host ".env já existe" }

Passo "7/7 Conferência"
& powershell -ExecutionPolicy Bypass -File "$PSScriptRoot\checar.ps1"
