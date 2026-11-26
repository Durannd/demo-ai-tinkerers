# Confere se a DEMO está pronta (rode antes de apresentar; funciona offline, exceto o teste opcional da API).
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\checar.ps1 [-Api]
#   -Api  faz 1 chamada de TEXTO (barata) ao Gemini só para provar que a chave e a internet funcionam.
param([switch]$Api)
Set-Location (Split-Path $PSScriptRoot -Parent)
$env:PYTHONUTF8 = "1"
$falhas = 0
function Ok($t)  { Write-Host "  [ok]   $t" -ForegroundColor Green }
function Mal($t) { Write-Host "  [FALTA] $t" -ForegroundColor Red; $script:falhas++ }

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok "ffmpeg no PATH" } else { Mal "ffmpeg no PATH (winget install Gyan.FFmpeg)" }
if (Get-Command ffprobe -ErrorAction SilentlyContinue) { Ok "ffprobe no PATH" } else { Mal "ffprobe no PATH" }
if (Get-Command node -ErrorAction SilentlyContinue) { Ok ("node " + (node -v)) } else { Mal "node (winget install OpenJS.NodeJS.LTS)" }
if (Test-Path ".venv\Scripts\python.exe") {
  Ok "venv .venv"
  $m = & .venv\Scripts\python.exe -c "import requests, jsonschema, PIL, numpy, cv2, faster_whisper; print('imports ok')" 2>&1
  if ($LASTEXITCODE -eq 0) { Ok "pacotes Python importam" } else { Mal "pacotes Python ($m)" }
} else { Mal ".venv (rode scripts\preparar.ps1)" }
if (Test-Path "render\node_modules\@remotion\renderer") { Ok "render\node_modules (Remotion)" } else { Mal "render\node_modules (npm install em render/)" }
if (Test-Path "render\node_modules\.remotion\chrome-headless-shell") { Ok "Chrome do Remotion" } else { Mal "Chrome do Remotion (cd render; npx remotion browser ensure)" }
if (Test-Path "assets\modelos\faster-whisper\models--Systran--faster-whisper-small") { Ok "modelo whisper small" } else { Mal "modelo whisper small (scripts\preparar.ps1)" }

# chave: confere sem imprimir
$chave = $null
if (Test-Path ".env") {
  $l = Select-String -Path ".env" -Pattern '^\s*GEMINI_API_KEY\s*=\s*(.+?)\s*$' | Select-Object -First 1
  if ($l) { $chave = $l.Matches[0].Groups[1].Value.Trim('"').Trim("'") }
}
if (-not $chave -and $env:GEMINI_API_KEY) { $chave = $env:GEMINI_API_KEY }
if ($chave) { Ok ("GEMINI_API_KEY definida (" + $chave.Length + " caracteres)") } else { Mal "GEMINI_API_KEY no .env" }

if (Test-Path "episodios\demo-reserva\final\demo-reserva_rascunho.mp4") { Ok "vídeo de reserva (plano C)" } else { Mal "episodios\demo-reserva\final\demo-reserva_rascunho.mp4" }
if (Test-Path "episodios\demo-reserva\audio\c01.mp3") { Ok "narração em cache do demo-reserva (plano B offline)" } else { Mal "audio do demo-reserva" }

if ($Api -and $chave) {
  try {
    $corpo = '{"contents":[{"parts":[{"text":"diga ok"}]}]}'
    $r = Invoke-RestMethod -Method Post -Uri "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent" -Headers @{ "x-goog-api-key" = $chave } -ContentType "application/json" -Body $corpo -TimeoutSec 30
    Ok "API do Gemini respondeu (internet + chave ok; não prova a cota do TTS)"
  } catch { Mal ("API do Gemini: " + $_.Exception.Message) }
}

if ($falhas -eq 0) { Write-Host "`nTUDO PRONTO." -ForegroundColor Green } else { Write-Host "`n$falhas pendência(s)." -ForegroundColor Red; exit 1 }
