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
    git -c advice.diverging=false pull --ff-only || call :yeniden_yazilmis
  ) || echo Otomatik guncelleme kapali: proje git ile indirilmemis. Bilgi icin KURULUM.md dosyasina bakin.
  call .venv\Scripts\activate.bat
  echo [2/3] Paketler ve veritabani guncelleniyor...
  python -m pip install -q -r requirements.txt
  python manage.py migrate --noinput >nul
  python manage.py yedekle >nul 2>&1
  echo [3/3] Ders Programi calisiyor: http://127.0.0.1:8000/
  echo Kapatmak icin bu pencerede Ctrl+C'ye basin ya da pencereyi kapatin.
  start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/"
  python manage.py runserver 127.0.0.1:8000
  exit /b
)

REM Sunucudaki gecmis yeniden yazildiysa (force push) hizli ileri sarma olmaz. Yerel degisiklik yoksa
REM en son surume gecilir; eski hal "onceki-surum" dalinda saklanir. Veritabani (db.sqlite3) git disidir.
:yeniden_yazilmis
git fetch >nul 2>&1 || (echo Guncelleme alinamadi: internete baglanilamadi. Mevcut surumle devam ediliyor. & exit /b)
git diff --quiet HEAD -- || (echo Guncelleme atlandi: yerel degisiklik var. Mevcut surumle devam ediliyor. & exit /b)
git branch -f onceki-surum HEAD >nul 2>&1
git reset --hard @{u} >nul && echo Sunucudaki surum yeniden duzenlenmisti; en son surume gecildi. Eski hal "onceki-surum" dalinda.
exit /b
