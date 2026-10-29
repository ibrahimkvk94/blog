"""Bir programın üretim girdisi özetini JSON olarak yazar (yedek karşılaştırmasında ayrı veritabanında çalışır).

    python manage.py girdi_ozeti --okul 7 [--ad "2026-2027 EÖY Güz"]
"""

import json

from django.core.management.base import BaseCommand

from timetable import input_diff
from timetable.models import School
from timetable.solver.builder import build_problem


class Command(BaseCommand):
    help = "Programın çözücü girdisi özetini yazar."

    def add_arguments(self, parser):
        parser.add_argument("--okul", type=int, required=True)
        parser.add_argument("--ad", default="")

    def handle(self, *args, **options):
        school = School.objects.filter(pk=options["okul"]).first()
        if options["ad"] and (school is None or school.name != options["ad"]):
            school = School.objects.filter(name=options["ad"]).first() or school
        if school is None:
            self.stdout.write(json.dumps({"error": "Program yedekte bulunamadı."}, ensure_ascii=False))
            return
        self.stdout.write(json.dumps({"name": school.name, "inputs": input_diff.fingerprint(build_problem(school))}, ensure_ascii=False))
