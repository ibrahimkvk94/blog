"""aSc öğretmen listesindeki "Zaman Tablosu" ızgaralarından müsaitlik aktarımı (aSc çevrim içi HTML biçimi)."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import asc_availability
from timetable.models import Availability, Period, School, Teacher

RED, GREEN, YELLOW = "rgb(255, 0, 0)", "rgb(0, 255, 0)", "rgb(255, 255, 0)"
HEAD = ('<div class="dt-container"><div class="asc-dt"><table><thead><tr><th class="" title=""></th><th class="" title=""></th>'
        '<th title="İsim">İsim<div class="resizer"></div></th><th title="Soy isim">Soy isim<div class="resizer"></div></th>'
        '<th title="Kısaltma">Kısaltma<div class="resizer"></div></th><th title="Toplam Saat">Toplam Saat</th>'
        '<th title="Zaman Tablosu">Zaman Tablosu</th><th title="16) *** Haftalık Boş Ders Sayısı Seçilen Değerden Fazla Olamaz.">'
        '<span>16) *** Haftalık</span></th></tr></thead></table></div><div class="asc-dt"><table><tbody>')


def row(first, last, short, days):
    grid = "".join('<div class="row">' + "".join(f'<div style="background-color: {c};"></div>' for c in day) + "</div>"
                   for day in days)
    return (f'<tr data-id="*1" class="rec"><td><img src="/global/pics/ui/teacher_32.svg"></td><td><span style="background-color: '
            f'rgb(255, 255, 255);"></span></td><td>{first}</td><td>{last}</td><td>{short}</td><td>8</td><td><div style="margin: -3px 0px;">'
            f'<div class="_RSS555"><style type="text/css">._RSS555 div.row {{display:flex;height:3px}}</style>{grid}</div></div></td>'
            '<td>Varsayılan</td><td>Herhangi</td></tr>')


def html(*rows):
    return HEAD + "".join(rows) + '<tr style="height: 4650px;"></tr></tbody></table></div></div>'


class AscAvailabilityTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(8):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
        self.ugur = Teacher.objects.create(school=self.school, first_name="Uğur", last_name="İÇÖZ", short="ASK Uğur İÇÖZ")
        self.emre = Teacher.objects.create(school=self.school, first_name="Emre", last_name="DARICI", short="")
        Availability.objects.create(school=self.school, teacher=self.emre, day=1, period=0, state=Availability.NO)  # eski kayıt
        full_red, full_green = [RED] * 8, [GREEN] * 8
        afternoon = [GREEN] * 5 + [RED] * 3
        self.text = html(
            row("Uğur", "İÇÖZ", "ASK Uğur İÇÖZ", [full_red, full_green, full_green, full_green, full_red]),
            row("Emre", "DARICI", "ASK Emre DARICI", [afternoon, full_green, [YELLOW] + [GREEN] * 7, full_green, afternoon]),
            row("Yok", "BÖYLEBİRİ", "ASK Yok", [full_green] * 5),
        )

    def test_parse_grid_and_names(self):
        rows = asc_availability.parse(self.text)
        self.assertEqual([(r["first"], r["last"], r["short"]) for r in rows],
                         [("Uğur", "İÇÖZ", "ASK Uğur İÇÖZ"), ("Emre", "DARICI", "ASK Emre DARICI"), ("Yok", "BÖYLEBİRİ", "ASK Yok")])
        self.assertEqual(len(rows[0]["grid"]), 5)
        self.assertEqual(rows[0]["grid"][0], ["no"] * 8)
        self.assertEqual(rows[1]["grid"][0], [""] * 5 + ["no"] * 3)
        self.assertEqual(rows[1]["grid"][2][0], "maybe")

    def test_plan_matches_by_short_or_name(self):
        items = asc_availability.plan(self.school, asc_availability.parse(self.text))
        self.assertEqual(items[0]["teacher"], self.ugur)          # kısa adla
        self.assertEqual(items[1]["teacher"], self.emre)          # ad soyadla (kısa ad boş)
        self.assertIsNone(items[2]["teacher"])
        self.assertTrue(items[2]["error"])
        self.assertEqual(items[0]["closed"], 16)
        self.assertEqual((items[1]["closed"], items[1]["maybe"]), (6, 1))
        self.assertEqual(items[1]["changed"], 8)  # 7 yeni + eski Salı 1. saat açılır

    def test_import_replaces_selected_availability(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:availability_import", args=[self.school.pk])
        preview = self.client.post(url, {"action": "preview", "text": self.text})
        self.assertContains(preview, "2</b> öğretmen eşleşti")
        self.client.post(url, {"action": "import", "text": self.text, "sec": ["0", "1"]})
        ugur = set(Availability.objects.filter(teacher=self.ugur).values_list("day", "period", "state"))
        self.assertEqual(ugur, {(d, p, "no") for d in (0, 4) for p in range(8)})
        emre = set(Availability.objects.filter(teacher=self.emre).values_list("day", "period", "state"))
        self.assertNotIn((1, 0, "no"), emre)  # eski kayıt aSc ızgarasıyla değişti
        self.assertIn((2, 0, "maybe"), emre)
        self.assertEqual(len(emre), 7)

    def test_unselected_teacher_untouched(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:availability_import", args=[self.school.pk])
        self.client.post(url, {"action": "import", "text": self.text, "sec": ["0"]})
        self.assertEqual(list(Availability.objects.filter(teacher=self.emre).values_list("day", "period")), [(1, 0)])
