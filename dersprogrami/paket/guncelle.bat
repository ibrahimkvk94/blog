@echo off
REM Ders Programi - kapali agda guncelleme. Yeni DersProgrami-*.zip dosyasini bu klasore kopyalayin
REM ve bu dosyaya cift tiklayin. Veritabani (db.sqlite3), .env ve yedekler korunur; once yedek alinir.
REM Kendini once gecici klasore kopyalar: guncelleme bu dosyanin uzerine yazsa da calisma bozulmaz.
if /i not "%~1"=="--gecici" (
  copy /y "%~f0" "%TEMP%\dersprogrami_guncelle.bat" >nul
  "%TEMP%\dersprogrami_guncelle.bat" --gecici "%~dp0"
)
set "HEDEF=%~2"
cd /d "%HEDEF%"
set "PY=%HEDEF%python\python.exe"
set "ZIP="
for /f "delims=" %%f in ('dir /b /o-d DersProgrami-*.zip 2^>nul') do if not defined ZIP set "ZIP=%%f"
if not defined ZIP (
  echo Bu klasorde DersProgrami-*.zip bulunamadi. Yeni surumun zip dosyasini buraya kopyalayin.
  pause
  exit /b 1
)
echo Guncelleme dosyasi: %ZIP%
echo Sunucu calisiyorsa durdurulacak. Devam etmek icin bir tusa basin (vazgecmek icin pencereyi kapatin).
pause >nul

echo [1/4] Sunucu durduruluyor ve yedek aliniyor...
schtasks /end /tn "Ders Programi" >nul 2>&1
if exist "%PY%" "%PY%" manage.py yedekle
if not exist yedekler mkdir yedekler
REM WAL kipindeki bekleyen yazmalar ana dosyaya islenir; boylece tek dosya kopyasi eksiksiz olur.
if exist db.sqlite3 "%PY%" -c "import sqlite3; c = sqlite3.connect('db.sqlite3'); c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()"
if exist db.sqlite3 copy /y db.sqlite3 "yedekler\db-guncelleme-oncesi.sqlite3" >nul

echo [2/4] Yeni surum aciliyor...
set "GECICI=%TEMP%\dersprogrami_yeni"
if exist "%GECICI%" rmdir /s /q "%GECICI%"
mkdir "%GECICI%"
tar -xf "%ZIP%" -C "%GECICI%" || goto :error
if not exist "%GECICI%\DersProgrami\manage.py" (
  echo Zip dosyasi beklenen yapida degil.
  goto :error
)

echo [3/4] Dosyalar kopyalaniyor...
robocopy "%GECICI%\DersProgrami" "%HEDEF%." /E /R:2 /W:2 /XF db.sqlite3 db.sqlite3-wal db.sqlite3-shm .env /XD yedekler /NFL /NDL /NJH /NJS /NP
if errorlevel 8 (
  echo Bazi dosyalar kopyalanamadi. Ders Programi penceresi acik kalmis olabilir; kapatip tekrar deneyin.
  goto :error
)
rmdir /s /q "%GECICI%"

echo [4/4] Veritabani guncelleniyor...
"%PY%" manage.py migrate --noinput || goto :error
"%PY%" manage.py collectstatic --noinput >nul
del "%ZIP%"
schtasks /query /tn "Ders Programi" >nul 2>&1 && schtasks /run /tn "Ders Programi" >nul && echo Sunucu yeniden baslatildi.
echo.
echo Guncelleme tamamlandi. Otomatik baslatma kullanmiyorsaniz baslat.bat ile acin.
pause
exit /b 0

:error
echo.
echo Guncelleme tamamlanamadi. Veritabani yedegi: yedekler\db-guncelleme-oncesi.sqlite3
pause
exit /b 1
