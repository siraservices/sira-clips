# Sira Clips - one-time setup on a Windows PC.
# Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "== Sira Clips setup ==" -ForegroundColor Cyan

# 1. ffmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "Installing ffmpeg..."
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    Write-Host "ffmpeg installed. Close and reopen this terminal, then run setup again." -ForegroundColor Yellow
    exit 0
}

# 2. Python 3.11+
$py = $null
foreach ($v in "3.13", "3.12", "3.11") {
    try { & py -$v -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = $v; break } } catch {}
}
if (-not $py) {
    Write-Host "Installing Python 3.12..."
    winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements
    $py = "3.12"
}

# 3. venv + packages
if (-not (Test-Path ".venv")) { & py -$py -m venv .venv }
$vpy = ".\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip -q
& $vpy -m pip install -q -r requirements.txt
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    Write-Host "NVIDIA GPU found; installing CUDA libraries for faster transcription..."
    & $vpy -m pip install -q nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
}

# 4. Face detection model
New-Item -ItemType Directory -Force models, inbox, work, output, brand\fonts | Out-Null
$model = "models\face_detection_yunet_2023mar.onnx"
if (-not (Test-Path $model)) {
    try {
        Invoke-WebRequest -UseBasicParsing -OutFile $model `
          "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
    } catch { Write-Host "Could not download YuNet; falling back to the built-in face detector." -ForegroundColor Yellow }
}

& $vpy -c "import faster_whisper, cv2; print('Python packages OK')"
Write-Host "Done. Put a video in inbox\, open Claude Code here, and ask for clips." -ForegroundColor Green
