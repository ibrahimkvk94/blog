"""aSc kart ilişkilerini yapıştırarak aktarma."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import asc_relations
from timetable.models import CardRelationship, Lesson, Period, School, SchoolClass, Subject, Teacher

HTML = """<div class="dt-container"><table><tbody>
<tr data-id="*1" class="rec dt-selected"><td>1</td><td><img src="/timetable/pics/app/relations/importance_strict_16.png"></td><td></td>
<td>Tüm Sınıflar - BİL103, BİL103</td><td>Dersler Ardarda Yerleştirilmelidir</td><td></td><td></td></tr>
<tr data-id="*2" class="rec dt-selected"><td>2</td><td><img src="/timetable/pics/app/relations/importance_strict_16.png"></td><td></td>
<td>Tüm Sınıflar - BİL103, BİL103</td><td>Dersler Ardarda Yerleştirilmelidir</td><td></td><td></td></tr>
<tr data-id="*3" class="rec dt-selected"><td>3</td><td><img src="/timetable/pics/app/relations/importance_normal_16.png"></td><td></td>
<td>Kr.Tm.İşl., 1SVN - BSB203, İŞL299</td><td>Seçilen Derslerin Seçilmiş Her Sınıfla Aynı Zamanda Olması Gerekir</td><td></td><td></td></tr>
<tr data-id="*4" class="rec dt-selected item-out"><td>4</td><td><img src="/timetable/pics/app/relations/importance_high_16.png"></td>
<td><img src="/timetable/pics/app/office/stop_32.png"></td><td>a_60</td><td>00) Kartlar Seçilen Saatlerde Olmalıdır.</td><td>BİL103, BİL103</td><td></td></tr>
<tr data-id="*5" class="rec dt-selected"><td>5</td><td><img src="/timetable/pics/app/relations/importance_strict_16.png"></td><td></td>
<td>Tüm Öğretmenler</td><td>06) ** Günlük Ders Sayısı Seçilen Değerden Fazla Olamaz.</td><td>6 8</td><td></td></tr>
<tr data-id="*6" class="rec dt-selected"><td>6</td><td><img src="/timetable/pics/app/relations/importance_strict_16.png"></td><td></td>
<td>Tüm Sınıflar - TBE201, SBE201</td><td>Dersler Ardarda Yerleştirilmelidir</td><td></td><td></td></tr>
<tr data-id="*7" class="rec dt-selected"><td>7</td><td><img src="/timetable/pics/app/relations/importance_strict_16.png"></td><td></td>
<td>Tüm Sınıflar - XYZ1</td><td>Bilinmeyen bir kural türü</td><td></td><td></td></tr>
</tbody></table></div>"""


class AscRelationshipImportTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=5)
        for i in range(6):
            Period.objects.create(school=self.school, index=i, name=str(i + 1))
        self.c1 = SchoolClass.objects.create(school=self.school, name="1.KISIM", short="1SVN")
        self.c2 = SchoolClass.objects.create(school=self.school, name="2.KISIM", short="2SVN")
        self.kr = SchoolClass.objects.create(school=self.school, name="Kr.Tm.İşl.")
        teacher = Teacher.objects.create(school=self.school, first_name="A", last_name="B")

        def lesson(name, short, cls, hours=1):
            subject = Subject.objects.create(school=self.school, name=name, short=short)
            obj = Lesson.objects.create(school=self.school, subject=subject, periods_per_week=hours, card_length=hours)
            obj.classes.set([cls])
            obj.teachers.set([teacher])
            return obj

        self.bil = [lesson("Algoritma", "BİL103", c) for c in (self.c1, self.c2)]
        self.bil_u = [lesson("Algoritma (U)", "BİL103", c, 2) for c in (self.c1, self.c2)]
        self.bsb = lesson("Savaş Felsefesi", "BSB203", self.c1, 2)
        self.isl = lesson("Bilgi ve Belge", "İŞL299", self.kr, 2)
        self.tbe = lesson("Beden 3", "TBE201", self.c1, 2)
        self.sbe = lesson("Savaş Beden 2", "SBE201", self.c1)

    def test_parse_html(self):
        rows = asc_relations.parse(HTML)
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[2]["importance"], CardRelationship.NORMAL)
        self.assertFalse(rows[3]["active"])
        self.assertEqual(rows[4]["params"], "6 8")

    def test_parse_tab_text(self):
        rows = asc_relations.parse("1\tTüm Sınıflar - BİL103, BİL103\tDersler Ardarda Yerleştirilmelidir\n2\tTüm Öğretmenler\t06) ** Günlük Ders Sayısı Seçilen Değerden Fazla Olamaz.\t6 8")
        self.assertEqual([r["scope"] for r in rows], ["Tüm Sınıflar - BİL103, BİL103", "Tüm Öğretmenler"])

    def test_plan(self):
        proposals = asc_relations.plan(self.school, asc_relations.parse(HTML))
        ok = [p for p in proposals if not p["error"]]
        by_row = {}
        for p in proposals:
            by_row.setdefault(p["row"], []).append(p)
        # 1: her sınıfta teori + uygulama, sırasız art arda
        self.assertEqual([p["condition"] for p in by_row["1"]], [CardRelationship.CONSECUTIVE] * 2)
        self.assertEqual({tuple(sorted(p["lessons"])) for p in by_row["1"]},
                         {tuple(sorted((a.id, b.id))) for a, b in zip(self.bil, self.bil_u)})
        self.assertIn("tekrar", by_row["2"][0]["error"])
        # 3: iki sınıfın dersleri aynı anda, yumuşak
        self.assertEqual(by_row["3"][0]["condition"], CardRelationship.SAME_TIME)
        self.assertEqual(set(by_row["3"][0]["lessons"]), {self.bsb.id, self.isl.id})
        self.assertEqual(by_row["3"][0]["importance"], CardRelationship.NORMAL)
        # 4: harita gerekir → devre dışı
        self.assertEqual(by_row["4"][0]["condition"], CardRelationship.ONLY_IN_MAP)
        self.assertFalse(by_row["4"][0]["active"])
        # 5: her öğretmen günde en fazla 6 saat, tüm hücreler
        rule = by_row["5"][0]
        self.assertEqual((rule["condition"], rule["param"], rule["apply_to"]), (CardRelationship.RANGE_MAX_PER_DAY, 6, CardRelationship.EACH_TEACHER))
        self.assertEqual(len(rule["time_map"]), 30)
        # 6: farklı kodlar sıralı
        self.assertEqual(by_row["6"][0]["condition"], CardRelationship.CONSECUTIVE_ORDERED)
        self.assertEqual(by_row["6"][0]["lessons"], [self.tbe.id, self.sbe.id])
        self.assertIn("desteklenmiyor", by_row["7"][0]["error"])
        self.assertEqual(len(ok), 6)

    def test_view_preview_and_import(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:relationship_import", args=[self.school.pk])
        page = self.client.post(url, {"action": "preview", "text": HTML})
        self.assertContains(page, "ilişki önerisi")
        self.client.post(url, {"action": "import", "text": HTML, "sec": ["0", "1", "3", "4"]})
        self.assertEqual(self.school.relationships.count(), 4)
        self.assertEqual(self.school.relationships.filter(active=False).count(), 1)
        # Aynısını yeniden yapıştırınca "zaten var" çıkar
        again = asc_relations.plan(self.school, asc_relations.parse(HTML))
        self.assertTrue(any("zaten var" in p["error"] for p in again))
