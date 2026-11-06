"""Veritabanının tutarlı yedeği (SQLite yedekleme API'si; WAL kipinde dosya kopyalamak eksik yedek verebilir).

    .venv\\Scripts\\python.exe manage.py veritabani_yedekle            # yedekler\\db_YYYYMMDD_HHMMSS.sqlite3
    .venv\\Scripts\\python.exe manage.py veritabani_yedekle --sakla 30  # en yeni 30 yedek kalır
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Veritabanının çalışırken bile tutarlı bir yedeğini alır."

    def add_arguments(self, parser):
        parser.add_argument("--klasor", default=str(settings.BASE_DIR / "yedekler"))
        parser.add_argument("--sakla", type=int, default=30, help="Saklanacak en yeni yedek sayısı (0 = hepsi)")

    def handle(self, *args, **options):
        klasor = Path(options["klasor"])
        klasor.mkdir(parents=True, exist_ok=True)
        hedef = klasor / f"db_{datetime.now():%Y%m%d_%H%M%S}.sqlite3"
        connection.ensure_connection()
        with sqlite3.connect(hedef) as yedek:
            connection.connection.backup(yedek)
        yedek.close()
        if options["sakla"]:
            for eski in sorted(klasor.glob("db_????????_??????.sqlite3"))[: -options["sakla"]]:
                eski.unlink()
        self.stdout.write(f"Yedek alındı: {hedef}")
