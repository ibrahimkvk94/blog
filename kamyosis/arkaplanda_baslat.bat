@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Siteyi penceresiz baslatir. Ciktilar: kayitlar\sunucu.log
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo KAMYOSIS zaten calisiyor ^(8000 portu kullanimda^).
  timeout /t 4 >nul
  exit /b
)
start "" ".venv\Scripts\pythonw.exe" yayinla.py
echo KAMYOSIS arka planda baslatildi: http://127.0.0.1:8000
timeout /t 3 >nul
