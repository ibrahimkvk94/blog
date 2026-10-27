@echo off
REM Ders Programi - calistir (Windows). Bu dosyaya cift tiklayin; kapatmak icin pencereyi kapatin.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo Once kurulum.bat dosyasini calistirin.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python manage.py migrate --noinput >nul
echo Ders Programi calisiyor: http://127.0.0.1:8000/
echo Kapatmak icin bu pencerede Ctrl+C'ye basin ya da pencereyi kapatin.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
python manage.py runserver 127.0.0.1:8000
