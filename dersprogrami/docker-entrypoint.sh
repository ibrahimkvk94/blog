#!/bin/sh
# ROLE=web (varsayılan) | worker | backup
set -e
case "${ROLE:-web}" in
  worker)
    # Veritabanı hazır olana kadar bekle, sonra kuyruğu işle.
    until python manage.py migrate --check >/dev/null 2>&1; do sleep 3; done
    exec python manage.py calisan --paralel "${WORKER_PARALLEL:-1}"
    ;;
  backup)
    until python manage.py migrate --check >/dev/null 2>&1; do sleep 3; done
    # Her gün bir yedek (BACKUP_KEEP kadar saklanır).
    while true; do python manage.py yedekle || true; sleep "${BACKUP_INTERVAL:-86400}"; done
    ;;
  *)
    python manage.py migrate --noinput
    # İlk çalıştırmada merkez yönetici hesabı (DJANGO_SUPERUSER_USERNAME / _PASSWORD verilmişse).
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
      python manage.py createsuperuser --noinput --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null || true
    fi
    # Çalışan kipinde üretim ayrı süreçte olduğundan web birden çok süreçle çalışabilir.
    if [ "${TIMETABLE_JOB_BACKEND:-thread}" = "worker" ]; then WORKERS="${WEB_WORKERS:-3}"; else WORKERS=1; fi
    exec gunicorn config.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers "$WORKERS" --threads 8 --timeout 120
    ;;
esac
