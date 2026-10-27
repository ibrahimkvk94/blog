@echo off
REM Ders Programi - calistir (Windows). Bu dosyaya cift tiklayin; kapatmak icin pencereyi kapatin.
REM Govde tek blok halindedir: Windows blogu bastan okur, boylece guncelleme bu dosyayi degistirse de
REM o anki calisma bozulmaz; yeni surum bir sonraki acilista devreye girer.
cd /d "%~dp0"
(
  if not exist .venv\Scripts\activate.bat (
    echo Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
  )
  echo [1/3] Guncellemeler kontrol ediliyor...
  git --version >nul 2>&1 && git rev-parse --is-inside-work-tree >nul 2>&1 && (
    git pull --ff-only || echo Guncelleme alinamadi: internet yok ya da yerel degisiklik var. Mevcut surumle devam ediliyor.
  ) || echo Otomatik guncelleme kapali: proje git ile indirilmemis. Bilgi icin KURULUM.md dosyasina bakin.
  call .venv\Scripts\activate.bat
  echo [2/3] Paketler ve veritabani guncelleniyor...
  python -m pip install -q -r requirements.txt
  python manage.py migrate --noinput >nul
  echo [3/3] Ders Programi calisiyor: http://127.0.0.1:8000/
  echo Kapatmak icin bu pencerede Ctrl+C'ye basin ya da pencereyi kapatin.
  start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
  python manage.py runserver 127.0.0.1:8000
  exit /b
)
