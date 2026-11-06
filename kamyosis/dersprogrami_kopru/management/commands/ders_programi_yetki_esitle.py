from django.core.management.base import BaseCommand

from dersprogrami_kopru.yetki import hepsini_esitle
from timetable.models import Membership


class Command(BaseCommand):
    help = "Ders Programı modülü üyeliklerini KAMYOSİS yetkilerinden yeniden üretir."

    def handle(self, *args, **options):
        hepsini_esitle()
        self.stdout.write(f"Eşitlendi: {Membership.objects.count()} üyelik.")
