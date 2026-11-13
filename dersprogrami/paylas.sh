#!/bin/sh
# Ders Programı – ağa açık çalıştır (Linux / macOS): sh paylas.sh   · kapatmak için Ctrl+C
# Tailscale ya da yerel ağdaki bilgisayarlar bağlanır (paylas.bat'ın karşılığı). Güncelleme, veritabanı hazırlığı ve
# sunucu baslat.py'dedir; Merkez → Sistem güncelleme sayfasından güncellenince program kapanmadan yeniden başlar.
cd "$(dirname "$0")" || exit 1
[ -d .venv ] || { echo "Önce kurulum yapın: sh kurulum.sh"; exit 1; }
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  echo "Not: güvenlik duvarı (ufw) açık. 8000 kapısını bir kez açın:"
  echo "     Tailscale ağı:  sudo ufw allow from 100.64.0.0/10 to any port 8000 proto tcp"
  echo "     Yerel ağ:       sudo ufw allow from 192.168.0.0/16 to any port 8000 proto tcp   (ağınız 10.x ise 10.0.0.0/8)"
fi
. .venv/bin/activate
exec python baslat.py paylas
