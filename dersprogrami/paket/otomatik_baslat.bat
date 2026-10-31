@echo off
REM Ders Programi - bilgisayar acilinca (oturum acilmasa da) sunucuyu arka planda baslatir.
REM Kaldirmak icin:  otomatik_baslat.bat kaldir
cd /d "%~dp0"
net session >nul 2>&1 || (
  echo Yonetici izni isteniyor...
  if "%~1"=="" (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  ) else (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%~1' -Verb RunAs"
  )
  exit /b
)

if /i "%~1"=="kaldir" (
  schtasks /end /tn "Ders Programi" >nul 2>&1
  schtasks /delete /tn "Ders Programi" /f && echo Otomatik baslatma kaldirildi.
  pause
  exit /b
)

netsh advfirewall firewall show rule name="Ders Programi" >nul 2>&1 || netsh advfirewall firewall add rule name="Ders Programi" dir=in action=allow protocol=TCP localport=8000 profile=any >nul
schtasks /create /tn "Ders Programi" /tr "\"%~dp0baslat.bat\"" /sc onstart /ru SYSTEM /rl HIGHEST /f || goto :error
schtasks /run /tn "Ders Programi" >nul
echo.
echo Tamam: Ders Programi bilgisayar her acildiginda arka planda baslayacak ve su an baslatildi.
echo Durdurmak icin:   schtasks /end /tn "Ders Programi"
echo Kaldirmak icin:   otomatik_baslat.bat kaldir
pause
exit /b 0

:error
echo Gorev olusturulamadi.
pause
exit /b 1
