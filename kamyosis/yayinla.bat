@echo off
chcp 65001 >nul
cd /d "%~dp0"
title KAMYOSIS
".venv\Scripts\python.exe" yayinla.py %*
pause
