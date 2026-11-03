"""Bölüm/kısım tanımları değiştiğinde (ör. yeni bölüm öneki) mevcut programa yeniden uygular.

    python manage.py program_tanim_guncelle
"""

from django.core.management.base import BaseCommand, CommandError

from program.asc import tanimlari_guncelle
from program.models import ProgramSurumu


class Command(BaseCommand):
    help = "Ders/kısım bölümlerini, kısım türlerini ve öğretmenlerin tahmini bölümlerini yeniden hesaplar."

    def add_arguments(self, parser):
        parser.add_argument("--surum", type=int, help="Program sürümü (varsayılan: bugün geçerli, yoksa son yüklenen)")

    def handle(self, *args, **opts):
        if opts["surum"]:
            surum = ProgramSurumu.objects.filter(pk=opts["surum"]).first()
        else:
            surum = ProgramSurumu.objects.gecerli() or ProgramSurumu.objects.first()
        if surum is None:
            raise CommandError("Program sürümü bulunamadı.")
        tanimlari_guncelle(surum)
        self.stdout.write(self.style.SUCCESS(f"Tanımlar güncellendi: {surum.ad}"))
