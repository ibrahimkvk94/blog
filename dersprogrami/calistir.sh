#!/bin/sh
# Ders Programı – çalıştır (macOS / Linux): sh calistir.sh   · kapatmak için Ctrl+C
# Güncelleme, veritabanı hazırlığı ve sunucu baslat.py'dedir: Merkez → Sistem güncelleme sayfasından
# güncellenince program kapanmadan yeniden başlar.
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || { echo "Önce kurulum yapın: sh kurulum.sh"; exit 1; }
. .venv/bin/activate
exec python baslat.py yerel
