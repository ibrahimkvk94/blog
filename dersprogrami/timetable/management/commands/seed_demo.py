from django.core.management.base import BaseCommand

from timetable.demo import create_demo_school


class Command(BaseCommand):
    help = "Örnek bir lise verisi oluşturur."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Örnek Anadolu Lisesi")

    def handle(self, *args, **options):
        school = create_demo_school(options["name"])
        self.stdout.write(self.style.SUCCESS(f"Okul oluşturuldu: {school} (id={school.id})"))
