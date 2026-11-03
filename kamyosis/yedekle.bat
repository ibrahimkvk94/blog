@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Veritabaninin tutarli yedegini yedekler\ klasorune alir (site calisirken de alinabilir). En yeni 30 yedek saklanir.
.venv\Scripts\python.exe manage.py veritabani_yedekle
timeout /t 5 >nul
