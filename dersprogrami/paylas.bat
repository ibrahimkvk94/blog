@echo off
REM Ders Programi - baskalarinin da baglanabilecegi sekilde calistir (Tailscale / yerel ag).
REM calistir.bat yerine bunu acin; ikisini ayni anda acmayin (ayni kapiyi, 8000'i kullanirlar).
REM Guncelleme ve sunucu baslat.py'dedir: Merkez -> Sistem guncelleme sayfasindan guncellenince
REM program pencere kapanmadan yeniden baslar.
REM Govde tek blok halindedir: Windows blogu bastan okur, boylece guncelleme bu dosyayi degistirse de
REM o anki calisma bozulmaz; yeni surum bir sonraki acilista devreye girer.
cd /d "%~dp0"
(
  if not exist .venv\Scripts\activate.bat (
    echo Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
  )
  echo Guvenlik duvari: 8000 kapisi yalnizca Tailscale agina aciliyor...
  netsh advfirewall firewall show rule name="Ders Programi (Tailscale)" >nul 2>&1 && (
    echo        Kural zaten var.
  ) || (
    netsh advfirewall firewall add rule name="Ders Programi (Tailscale)" dir=in action=allow protocol=TCP localport=8000 remoteip=100.64.0.0/10 profile=any >nul 2>&1 && (
      echo        Kural eklendi.
    ) || (
      echo        Kural eklenemedi: yonetici yetkisi gerekiyor. Bu dosyaya bir kez sag tiklayip
      echo        "Yonetici olarak calistir" deyin; sonraki acilislarda gerekmez.
    )
  )
  call .venv\Scripts\activate.bat
  python baslat.py paylas
  echo.
  echo Sunucu durdu. Yukaridaki mesaji okuyun; pencereyi kapatmak icin bir tusa basin.
  pause >nul
  exit /b
)
