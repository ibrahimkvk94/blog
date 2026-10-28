@echo off
REM Ders Programi - sunucuyu baslatir (kapali ag paketi). Bu pencere acik kaldikca program agda calisir.
cd /d "%~dp0"
set "PY=%~dp0python\python.exe"
if not exist .env (
  echo Once kurulum.bat dosyasini calistirin.
  pause
  exit /b 1
)
"%PY%" manage.py migrate --noinput >nul
"%PY%" manage.py collectstatic --noinput >nul
"%PY%" manage.py sunucu
