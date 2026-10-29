@echo off
REM Ders Programi - baskalarinin da baglanabilecegi sekilde calistir (Tailscale / yerel ag).
REM calistir.bat yerine bunu acin; ikisini ayni anda acmayin (ayni kapiyi, 8000'i kullanirlar).
REM Govde tek blok halindedir: Windows blogu bastan okur, boylece guncelleme bu dosyayi degistirse de
REM o anki calisma bozulmaz; yeni surum bir sonraki acilista devreye girer.
cd /d "%~dp0"
(
  if not exist .venv\Scripts\activate.bat (
    echo Once kurulum.bat dosyasini calistirin.
    pause
    exit /b 1
  )
  echo [1/4] Guncellemeler kontrol ediliyor...
  git --version >nul 2>&1 && git rev-parse --is-inside-work-tree >nul 2>&1 && (
    git -c advice.diverging=false pull --ff-only || call :yeniden_yazilmis
  ) || echo Otomatik guncelleme kapali: proje git ile indirilmemis.
  call .venv\Scripts\activate.bat
  echo [2/4] Paketler ve veritabani guncelleniyor...
  python -m pip install -q -r requirements.txt
  REM Ag kullanimi icin bu bilgisayara ozel gizli anahtar (.env'de yoksa bir kez uretilir).
  python -c "import pathlib, secrets; p = pathlib.Path('.env'); t = p.read_text(encoding='utf-8') if p.exists() else ''; 'DJANGO_SECRET_KEY=' in t or p.write_text(t + ('' if t.endswith(chr(10)) or not t else chr(10)) + 'DJANGO_SECRET_KEY=' + secrets.token_urlsafe(50) + chr(10), encoding='utf-8')"
  REM Yalnizca bu pencere icin: hata ayiklama kapali, Tailscale adi/IP'siyle gelen isteklere izin.
  set "DJANGO_DEBUG=0"
  set "DJANGO_ALLOWED_HOSTS=*"
  python manage.py migrate --noinput >nul
  python manage.py collectstatic --noinput >nul
  python manage.py yedekle >nul 2>&1
  echo [3/4] Guvenlik duvari: 8000 kapisi yalnizca Tailscale agina aciliyor...
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
  echo [4/4] Sunucu baslatiliyor. Asagida yazan Tailscale adresini baglanacak kisilere verin.
  start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000/"
  python manage.py sunucu --port 8000
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
