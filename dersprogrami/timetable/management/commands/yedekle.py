"""Tüm verinin yedeğini alır (eski yedekler BACKUP_KEEP sayısına göre silinir).

    python manage.py yedekle
"""

from django.core.management.base import BaseCommand

from timetable import backup


class Command(BaseCommand):
    help = "Tüm verinin sıkıştırılmış yedeğini alır."

    def handle(self, *args, **options):
        path = backup.create()
        self.stdout.write(f"Yedek alındı: {path}")
