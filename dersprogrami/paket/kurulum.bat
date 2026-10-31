@echo off
REM Ders Programi - kapali ag kurulumu (internet gerekmez). Sunucu olacak bilgisayarda bir kez cift tiklayin.
REM Python ve tum paketler "python" klasorundedir; bilgisayara ayrica bir sey kurulmaz.
cd /d "%~dp0"
set "PY=%~dp0python\python.exe"
if not exist "%PY%" (
  echo "python" klasoru bulunamadi. Zip dosyasini eksiksiz actiginizdan emin olun.
  pause
  exit /b 1
)

echo [1/5] Ayarlar hazirlaniyor...
if not exist .env (
  "%PY%" -c "import secrets; open('.env', 'w', encoding='utf-8').write('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(50) + '\nDJANGO_DEBUG=0\nDJANGO_ALLOWED_HOSTS=*\nSUNUCU_PORT=8000\n')" || goto :error
  echo        .env olusturuldu ^(gizli anahtar bu bilgisayarda uretildi^).
) else (
  echo        Mevcut .env korunuyor.
)

echo [2/5] Veritabani hazirlaniyor...
"%PY%" manage.py migrate --noinput || goto :error
"%PY%" manage.py collectstatic --noinput >nul || goto :error

echo [3/5] Ornek veri
set /p DEMO=Ornek okul verisi yuklensin mi? (E/H):
if /i "%DEMO%"=="E" "%PY%" manage.py seed_demo

echo [4/5] Yonetici hesabi olusturuluyor. Kullanici adi ve parola sorulacak
echo        (parola yazarken ekranda gorunmez, bu normaldir).
"%PY%" manage.py createsuperuser

echo [5/5] Guvenlik duvarinda 8000 numarali kapi aciliyor (diger bilgisayarlar baglanabilsin diye)...
netsh advfirewall firewall show rule name="Ders Programi" >nul 2>&1 && (
  echo        Kural zaten var.
) || (
  netsh advfirewall firewall add rule name="Ders Programi" dir=in action=allow protocol=TCP localport=8000 profile=any >nul 2>&1 && (
    echo        Kural eklendi.
  ) || (
    echo        Kural eklenemedi: yonetici yetkisi gerekiyor. Bu dosyaya sag tiklayip
    echo        "Yonetici olarak calistir" deyin ya da otomatik_baslat.bat ile birlikte eklenir.
  )
)

echo.
echo Kurulum tamamlandi.
echo  - Programi acmak icin baslat.bat dosyasina cift tiklayin; ekranda ag adresi yazar.
echo  - Bilgisayar acilinca kendiliginden baslamasi icin otomatik_baslat.bat (yonetici olarak).
pause
exit /b 0

:error
echo.
echo Bir hata olustu. Yukaridaki mesaji kontrol edin.
pause
exit /b 1
