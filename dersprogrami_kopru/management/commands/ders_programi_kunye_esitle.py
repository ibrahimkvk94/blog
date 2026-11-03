from django.core.management.base import BaseCommand

from dersprogrami_kopru.kunye import kunyeleri_esitle


class Command(BaseCommand):
    help = "Ders Programı öğretmenlerinin “ünvan / rütbe” alanını KAMYOSİS personel künyesinden yeniden yazar."

    def handle(self, *args, **options):
        self.stdout.write(f"Güncellenen öğretmen: {kunyeleri_esitle()}")
