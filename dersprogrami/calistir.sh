#!/bin/sh
# Ders Programı – çalıştır (macOS / Linux): sh calistir.sh   · kapatmak için Ctrl+C
# Gövde bir fonksiyondadır: kabuk onu baştan okur; güncelleme bu dosyayı değiştirse de o anki
# çalışma bozulmaz, yeni sürüm bir sonraki açılışta devreye girer.
# Sunucudaki geçmiş yeniden yazıldıysa (force push) hızlı ileri sarma olmaz. Yerel değişiklik yoksa en
# son sürüme geçilir; eski hal "onceki-surum" dalında saklanır. Veritabanı (db.sqlite3) git dışıdır.
update_rewritten() {
  git fetch >/dev/null 2>&1 || { echo "Güncelleme alınamadı (internet yok); mevcut sürümle devam ediliyor."; return; }
  git diff --quiet HEAD -- || { echo "Güncelleme atlandı: yerel değişiklik var; mevcut sürümle devam ediliyor."; return; }
  git branch -f onceki-surum HEAD >/dev/null 2>&1
  git reset --hard '@{u}' >/dev/null && echo "Sunucudaki sürüm yeniden düzenlenmişti; en son sürüme geçildi. Eski hal 'onceki-surum' dalında."
}

main() {
  cd "$(dirname "$0")" || exit 1
  [ -d .venv ] || { echo "Önce kurulum yapın: sh kurulum.sh"; exit 1; }
  echo "[1/3] Güncellemeler kontrol ediliyor..."
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -c advice.diverging=false pull --ff-only || update_rewritten
  else
    echo "Otomatik güncelleme kapalı: proje git ile indirilmemiş (bkz. KURULUM.md)."
  fi
  . .venv/bin/activate
  echo "[2/3] Paketler ve veritabanı güncelleniyor..."
  python -m pip install -q -r requirements.txt
  python manage.py migrate --noinput >/dev/null
  echo "[3/3] Ders Programı çalışıyor: http://127.0.0.1:8000/  (kapatmak için Ctrl+C)"
  ( sleep 3; (command -v open >/dev/null && open http://127.0.0.1:8000/) || (command -v xdg-open >/dev/null && xdg-open http://127.0.0.1:8000/) ) >/dev/null 2>&1 &
  python manage.py runserver 127.0.0.1:8000
}
main "$@"; exit
