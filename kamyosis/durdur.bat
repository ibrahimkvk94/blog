@echo off
chcp 65001 >nul
rem Arka planda (veya pencerede) calisan KAMYOSIS sunucusunu durdurur
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*yayinla.py*' -or $_.CommandLine -like '*manage.py*calisan*') -and $_.Name -like 'python*' }; if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; 'KAMYOSIS durduruldu.' } else { 'KAMYOSIS zaten calismiyor.' }"
timeout /t 3 >nul
