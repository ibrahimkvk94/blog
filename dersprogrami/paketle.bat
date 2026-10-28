@echo off
REM Ders Programi - kapali ag kurulum paketi olusturur. Internete bagli bir Windows bilgisayarda cift tiklayin.
REM Sonuc dist\DersProgrami-YYYYMMDD.zip dosyasidir; kapali aga bu dosyayi tasiyin.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0paket\paketle.ps1" %*
if errorlevel 1 (
  echo.
  echo Paket olusturulamadi. Yukaridaki mesaji kontrol edin.
)
pause
