@echo off
REM Ders Programi - calistir (Windows). Bu dosyaya cift tiklayin; kapatmak icin pencereyi kapatin.
REM Guncelleme, veritabani hazirligi ve sunucu baslat.py'dedir: Merkez -> Sistem guncelleme sayfasindan
REM guncellenince program pencere kapanmadan yeniden baslar.
REM Govde tek blok halindedir: Windows blogu bastan okur, boylece guncelleme bu dosyayi degistirse de
REM o anki calisma bozulmaz; yeni surum bir sonraki acilista devreye girer.
cd /d "%~dp0"
(
  if not exist .venv\Scripts\activate.bat (
    echo Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
  )
  call .venv\Scripts\activate.bat
  python baslat.py yerel
  echo.
  echo Program kapandi. Pencereyi kapatmak icin bir tusa basin.
  pause >nul
  exit /b
)
