@echo off
chcp 65001 >nul
rem Windows acilisinda otomatik baslatmayi kapatir (calisan sunucuyu durdurmaz; onun icin durdur.bat)
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\KAMYOSIS.lnk" 2>nul && echo Otomatik baslatma kaldirildi. || echo Otomatik baslatma zaten kurulu degil.
timeout /t 3 >nul
