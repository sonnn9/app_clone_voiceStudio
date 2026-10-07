@echo off
REM Build a portable single-file EXE:  dist\AudioStudioBatchTTS.exe
setlocal
cd /d "%~dp0"

if not exist .venv (
    echo Creating virtual environment...
    py -3.13 -m venv .venv || py -3 -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip >nul
python -m pip install -r requirements-dev.txt || goto :error

echo Running tests...
python -m pytest -q tests || goto :error

echo Building EXE...
pyinstaller --noconfirm --clean AudioStudioBatchTTS.spec || goto :error

REM Optional: ship ffmpeg.exe next to the EXE if one is provided in .\ffmpeg\
if exist ffmpeg\ffmpeg.exe copy /Y ffmpeg\ffmpeg.exe dist\ >nul

echo.
echo Done: dist\AudioStudioBatchTTS.exe
exit /b 0

:error
echo Build failed.
exit /b 1
