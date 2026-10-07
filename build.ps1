# Build a portable single-file EXE:  dist\AudioStudioBatchTTS.exe
#   powershell -ExecutionPolicy Bypass -File build.ps1 [-SkipTests] [-BundleFfmpeg]
param(
    [switch]$SkipTests,
    [switch]$BundleFfmpeg   # copy the ffmpeg.exe found on PATH next to the EXE
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { py -3 -m venv .venv }
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
    & $py -m pytest -q tests
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}

& $py -m PyInstaller --noconfirm --clean AudioStudioBatchTTS.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if (Test-Path "ffmpeg\ffmpeg.exe") {
    Copy-Item "ffmpeg\ffmpeg.exe" "dist\" -Force
} elseif ($BundleFfmpeg) {
    $ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if ($ff) { Copy-Item $ff "dist\" -Force; Write-Host "Bundled $ff" }
    else { Write-Warning "ffmpeg not found on PATH - not bundled" }
}
Write-Host "`nDone: dist\AudioStudioBatchTTS.exe"
