@echo off
REM Ders Programi - ilk kurulum (Windows). Bu dosyaya cift tiklayin.
cd /d "%~dp0"
set PY=python
python --version >nul 2>&1 || set PY=py -3
%PY% --version >nul 2>&1 || goto :nopython

echo [1/4] Sanal ortam olusturuluyor...
if not exist .venv\Scripts\activate.bat %PY% -m venv .venv || goto :error
call .venv\Scripts\activate.bat

echo [2/4] Paketler yukleniyor (internet gerekir, birkac dakika surebilir)...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt || goto :error

echo [3/4] Veritabani hazirlaniyor...
python manage.py migrate || goto :error
set /p DEMO=Ornek okul verisi yuklensin mi? (E/H): 
if /i "%DEMO%"=="E" python manage.py seed_demo

echo [4/4] Yonetici hesabi olusturuluyor. Kullanici adi ve parola sorulacak
echo        (parola yazarken ekranda gorunmez, bu normaldir).
python manage.py createsuperuser

echo.
echo Kurulum tamamlandi. Programi acmak icin calistir.bat dosyasina cift tiklayin.
pause
exit /b 0

:nopython
echo Python bulunamadi. https://www.python.org/downloads/ adresinden Python 3.12 ya da 3.13 kurun
echo ve kurulumda "Add python.exe to PATH" kutusunu isaretleyin.
pause
exit /b 1

:error
echo.
echo Bir hata olustu. Yukaridaki mesaji kontrol edin.
pause
exit /b 1
