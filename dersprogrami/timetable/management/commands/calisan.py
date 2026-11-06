"""Üretim ve okul geneli iyileştirme kuyruğunu işleyen çalışan süreç (TIMETABLE_JOB_BACKEND=worker).

    python manage.py calisan            # sürekli çalışır, sıradaki üretimleri tek tek işler
    python manage.py calisan --paralel 2
"""

import threading
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from timetable import jobs, school_improve


class Command(BaseCommand):
    help = "Sıradaki ders programı üretimlerini çalıştırır (çalışan süreç)."

    def add_arguments(self, parser):
        parser.add_argument("--paralel", type=int, default=1, help="Aynı anda çalıştırılacak üretim sayısı")
        parser.add_argument("--bir-kez", action="store_true", help="Sıradakileri bitirince çık (test/zamanlanmış görev)")

    def handle(self, *args, **options):
        slots = threading.Semaphore(max(1, options["paralel"]))
        running = []
        self.stdout.write(f"Çalışan başladı (paralel: {options['paralel']}).")
        while True:
            close_old_connections()
            running = [t for t in running if t.is_alive()]
            if slots.acquire(blocking=False):
                timetable = jobs.claim_next()
                improve = None if timetable is not None else school_improve.claim_next()
                if timetable is None and improve is None:
                    slots.release()
                    if options["bir_kez"] and not running:
                        return
                    time.sleep(1)
                    continue
                if timetable is not None:
                    self.stdout.write(f"Üretim başladı: #{timetable.pk} {timetable.name}")
                    task, label = (lambda t=timetable: jobs.run_claimed(t)), f"Üretim #{timetable.pk}"
                else:
                    self.stdout.write(f"Okul geneli iyileştirme başladı: #{improve.pk}")
                    task, label = (lambda j=improve: school_improve.run(j.pk)), f"İyileştirme #{improve.pk}"

                def work(task=task, label=label):
                    try:
                        close_old_connections()
                        task()
                    except Exception as exc:  # bir işteki hata çalışanı durdurmasın
                        self.stderr.write(f"{label} hata: {exc}")
                    finally:
                        connection.close()
                        slots.release()

                thread = threading.Thread(target=work, daemon=True)
                thread.start()
                running.append(thread)
            else:
                time.sleep(0.5)
