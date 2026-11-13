@echo off
chcp 65001 >nul
cd /d "%~dp0"
title KAMYOSIS (gelistirme)
".venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
pause
