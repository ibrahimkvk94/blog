from django.core.management.base import BaseCommand, CommandError

from timetable.models import School
from timetable.services import generate_timetable


class Command(BaseCommand):
    help = "Bir okul için ders programı üretir."

    def add_arguments(self, parser):
        parser.add_argument("school_id", type=int)
        parser.add_argument("--name", default="Komut satırı üretimi")
        parser.add_argument("--time-limit", type=int, default=None, help="saniye")
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--mode", choices=["strict", "relaxed"], default="strict", help="katı ya da gevşek (taslak)")

    def handle(self, *args, **options):
        try:
            school = School.objects.get(pk=options["school_id"])
        except School.DoesNotExist:
            raise CommandError("Okul bulunamadı.")
        timetable = generate_timetable(
            school, options["name"], time_limit=options["time_limit"], seed=options["seed"], mode=options["mode"]
        )
        for issue in timetable.report.get("issues", []):
            self.stdout.write(f"[{issue['level']}] {issue['message']}")
        solver = timetable.report.get("solver")
        if solver:
            self.stdout.write(f"Çözücü: {solver}")
        if timetable.report.get("error"):
            self.stdout.write(self.style.ERROR(timetable.report["error"]))
        if timetable.report.get("penalties"):
            self.stdout.write(f"Ceza dağılımı: {timetable.report['penalties']}")
        validation = timetable.report.get("validation")
        if validation:
            self.stdout.write(f"Doğrulama: {validation['stats']}, ihlal: {len(validation['violations'])}")
        style = self.style.SUCCESS if timetable.status == timetable.OK else self.style.WARNING if timetable.status == timetable.PARTIAL else self.style.ERROR
        self.stdout.write(style(f"{timetable} → {timetable.get_status_display()} (id={timetable.id})"))
