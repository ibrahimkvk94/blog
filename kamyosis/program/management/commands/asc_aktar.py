"""aSc Timetables XML dosyasını yeni bir taslak program sürümü olarak yükler.

    python manage.py asc_aktar aSc\\asctt2012.xml --ad "2026-2027 Güz"
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from program.asc import AscHatasi, ice_aktar


class Command(BaseCommand):
    help = "aSc Timetables XML dosyasını taslak program sürümü olarak yükler."

    def add_arguments(self, parser):
        parser.add_argument("dosya")
        parser.add_argument("--ad", help="Sürüm adı (varsayılan: dosya adı)")

    def handle(self, *args, **opts):
        yol = Path(opts["dosya"])
        if not yol.exists():
            raise CommandError(f"Dosya bulunamadı: {yol}")
        try:
            surum, rapor = ice_aktar(str(yol), surum_adi=opts["ad"] or yol.stem, kaynak_dosya=yol.name)
        except AscHatasi as e:
            raise CommandError(str(e)) from e
        self.stdout.write(self.style.SUCCESS(f"Taslak sürüm oluşturuldu: {surum.ad} (#{surum.pk})"))
        for ad, sayi in rapor.sayilar.items():
            self.stdout.write(f"  {ad:<40} {sayi:>5}")
        for u in rapor.uyarilar:
            self.stdout.write(self.style.WARNING(f"  ! {u}"))
