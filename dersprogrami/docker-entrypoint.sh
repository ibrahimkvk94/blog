#!/bin/sh
set -e
python manage.py migrate --noinput
# İlk çalıştırmada yönetici hesabı (DJANGO_SUPERUSER_USERNAME / _PASSWORD verilmişse).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  python manage.py createsuperuser --noinput --email "${DJANGO_SUPERUSER_EMAIL:-admin@example.com}" 2>/dev/null || true
fi
# Üretim işleri süreç içinde çalıştığı için tek süreç + çok iş parçacığı kullanılır.
exec gunicorn config.wsgi --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 8 --timeout 120
