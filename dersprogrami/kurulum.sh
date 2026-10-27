#!/bin/sh
# Ders Programı – ilk kurulum (macOS / Linux): sh kurulum.sh
set -e
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3 bulunamadı. https://www.python.org/downloads/ adresinden kurun."; exit 1; }

echo "[1/4] Sanal ortam oluşturuluyor..."
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate

echo "[2/4] Paketler yükleniyor (internet gerekir, birkaç dakika sürebilir)..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

echo "[3/4] Veritabanı hazırlanıyor..."
python manage.py migrate
printf "Örnek okul verisi yüklensin mi? (E/H): "
read DEMO
case "$DEMO" in [EeYy]*) python manage.py seed_demo ;; esac

echo "[4/4] Yönetici hesabı oluşturuluyor (parola yazarken ekranda görünmez, bu normaldir)."
python manage.py createsuperuser

echo
echo "Kurulum tamamlandı. Çalıştırmak için: sh calistir.sh"
