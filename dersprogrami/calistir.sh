#!/bin/sh
# Ders Programı – çalıştır (macOS / Linux): sh calistir.sh   · kapatmak için Ctrl+C
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Önce kurulum yapın: sh kurulum.sh"; exit 1; }
. .venv/bin/activate
python manage.py migrate --noinput >/dev/null
echo "Ders Programı çalışıyor: http://127.0.0.1:8000/  (kapatmak için Ctrl+C)"
( sleep 3; (command -v open >/dev/null && open http://127.0.0.1:8000/) || (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8000/) ) >/dev/null 2>&1 &
python manage.py runserver 127.0.0.1:8000
