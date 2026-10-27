"""Çok okullu yapı ve yetkilendirme."""

import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable.models import Institution, Membership, School
from timetable.services import generate_timetable
from timetable.tests.test_operations import build_school

M = Membership


class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = build_school()
        cls.other = School.objects.create(name="Başka okul")
        cls.timetable = generate_timetable(cls.school, "ilk", time_limit=10)
        cls.central = User.objects.create_superuser("merkez", password="parola-123456")
        cls.admin = User.objects.create_user("mudur", password="parola-123456")
        M.objects.create(user=cls.admin, institution=cls.school.institution, permissions=M.ALL)
        cls.viewer = User.objects.create_user("izleyici", password="parola-123456")
        M.objects.create(user=cls.viewer, institution=cls.school.institution, permissions=[])

    def test_login_page_and_school_list_filtering(self):
        self.assertEqual(self.client.get(reverse("timetable:login")).status_code, 200)
        self.assertTrue(self.client.login(username="mudur", password="parola-123456"))
        page = self.client.get(reverse("timetable:school_list"))
        self.assertContains(page, self.school.name)
        self.assertNotContains(page, "Başka okul")
        self.assertNotContains(page, "Merkez paneli")
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.other.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("timetable:central")).status_code, 403)
        self.assertEqual(self.client.post(reverse("timetable:create_demo")).status_code, 403)

    def test_viewer_can_read_but_not_edit(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:api_grid", args=[self.timetable.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:report_render", args=[self.timetable.pk]) + "?tur=carsaf").status_code, 200)
        card = self.timetable.cards.first()
        response = self.client.post(reverse("timetable:api_card_move", args=[card.pk]), json.dumps({"day": 0, "period": 0}), content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertIn("yetkiniz yok", response.json()["message"])
        response = self.client.post(reverse("timetable:data_new", args=[self.school.pk, "ders-adlari"]), {"name": "X"})
        self.assertEqual(response.status_code, 403)
        page = self.client.get(reverse("timetable:school_detail", args=[self.school.pk]))
        self.assertNotContains(page, "Ders dağıtımı")  # veri menüsü gizli
        self.assertEqual(self.client.get(reverse("timetable:institution_users", args=[self.school.institution_id])).status_code, 403)

    def test_delegation_is_limited_to_own_permissions(self):
        lead = User.objects.create_user("zumre", password="parola-123456")
        M.objects.create(user=lead, institution=self.school.institution, permissions=[M.DATA, M.USERS])
        self.client.force_login(lead)
        url = reverse("timetable:institution_users", args=[self.school.institution_id])
        response = self.client.post(url, {"action": "add", "username": "ogretmen1", "password": "Guclu-Parola-2026",
                                          "permissions": [M.DATA, M.PROGRAM, M.PUBLISH]})
        self.assertRedirects(response, url)
        member = M.objects.get(user__username="ogretmen1")
        self.assertEqual(member.permissions, [M.DATA])  # program/yayın verilemedi
        # Sizden yetkili kullanıcıyı (müdür) değiştiremez
        boss = M.objects.get(user=self.admin)
        self.client.post(url, {"action": "update", "membership": boss.pk, "permissions": []})
        boss.refresh_from_db()
        self.assertEqual(boss.permissions, M.ALL)
        # Kendi eklediğinin yetkisini değiştirebilir ve çıkarabilir
        self.client.post(url, {"action": "update", "membership": member.pk, "permissions": []})
        member.refresh_from_db()
        self.assertEqual(member.permissions, [])
        self.client.post(url, {"action": "password", "membership": member.pk, "password": "Yeni-Parola-2026"})
        self.assertTrue(User.objects.get(username="ogretmen1").check_password("Yeni-Parola-2026"))
        self.client.post(url, {"action": "remove", "membership": member.pk})
        self.assertFalse(M.objects.filter(pk=member.pk).exists())
        # Yeni kullanıcı yalnızca bu okulu görür
        self.client.force_login(User.objects.get(username="ogretmen1"))
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)

    def test_central_creates_school_with_admin(self):
        self.client.force_login(self.central)
        self.assertContains(self.client.get(reverse("timetable:central")), "Kurum ekle")
        response = self.client.post(reverse("timetable:central_school_new"), {
            "school_name": "Yeni Lise", "username": "yenimudur", "password": "Guclu-Parola-2026", "permissions": M.ALL,
        })
        self.assertRedirects(response, reverse("timetable:central"))
        institution = Institution.objects.get(name="Yeni Lise")
        membership = M.objects.get(institution=institution)
        self.assertEqual(membership.user.username, "yenimudur")
        self.client.force_login(membership.user)
        self.assertEqual(self.client.get(reverse("timetable:institution_users", args=[institution.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)

    def test_account_page(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse("timetable:account")), self.school.name)
        response = self.client.post(reverse("timetable:account"), {
            "old_password": "parola-123456", "new_password1": "Baska-Parola-2026", "new_password2": "Baska-Parola-2026",
        })
        self.assertRedirects(response, reverse("timetable:account"))
        self.assertTrue(User.objects.get(username="izleyici").check_password("Baska-Parola-2026"))


class InstitutionProgramTests(TestCase):
    """Kurum altında birden çok program, kurum içine aSc aktarımı, program kısıtı ve bağlı programlar."""

    def setUp(self):
        self.school = build_school()
        self.institution = self.school.institution
        self.manager = User.objects.create_user("kurum", password="parola-123456")
        M.objects.create(user=self.manager, institution=self.institution, permissions=M.ALL)
        self.client.force_login(self.manager)

    def test_program_new_and_import_into_institution(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from timetable.tests.test_asc_import import SAMPLE

        url = reverse("timetable:institution_detail", args=[self.institution.pk])
        page = self.client.get(url)
        self.assertContains(page, "aSc TimeTables")
        self.client.post(reverse("timetable:program_new", args=[self.institution.pk]), {"name": "2.YY", "copy_periods": self.school.pk})
        second = School.objects.get(name="2.YY")
        self.assertEqual(second.institution, self.institution)
        self.assertEqual(second.periods.count(), self.school.periods.count())

        response = self.client.post(reverse("timetable:program_import", args=[self.institution.pk]),
                                    {"file": SimpleUploadedFile("asc.xml", SAMPLE), "target": "new", "name": "MYO 1.YY"})
        imported = School.objects.get(name="MYO 1.YY")
        self.assertEqual(imported.institution, self.institution)
        self.assertEqual(Institution.objects.count(), 1)  # yeni kurum açılmadı
        self.assertIn("/program/", response["Location"])

        # Var olan programın yerine aktarma: ad korunur, kısıtlı üyelik yeni programa taşınır
        limited = User.objects.create_user("sinirli", password="parola-123456")
        membership = M.objects.create(user=limited, institution=self.institution, permissions=[])
        membership.programs.set([second])
        self.client.post(reverse("timetable:program_import", args=[self.institution.pk]),
                         {"file": SimpleUploadedFile("asc.xml", SAMPLE), "target": second.pk})
        self.assertFalse(School.objects.filter(pk=second.pk).exists())
        replaced = School.objects.get(name="2.YY")
        self.assertEqual(replaced.classes.count(), 2)
        self.assertEqual(list(membership.programs.all()), [replaced])

        # Ana sayfa kurumu ve programlarını gösterir
        home = self.client.get(reverse("timetable:school_list"))
        for name in (self.school.name, "2.YY", "MYO 1.YY"):
            self.assertContains(home, name)

    def test_program_restricted_membership(self):
        other = School.objects.create(name="Gece", institution=self.institution)
        user = User.objects.create_user("gece", password="parola-123456")
        membership = M.objects.create(user=user, institution=self.institution, permissions=[M.DATA])
        membership.programs.set([other])
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[other.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse("timetable:program_new", args=[self.institution.pk]), {"name": "X"}).status_code, 403)

    def test_linked_programs_block_shared_teacher_and_room(self):
        from timetable.solver.builder import build_problem

        timetable = generate_timetable(self.school, "ilk", time_limit=10)
        School.objects.filter(pk=self.school.pk).update(active_timetable=timetable)
        other = School.objects.create(name="Gece", institution=self.institution)
        teacher = self.school.teachers.first()
        busy = {(c.day, c.period + i) for c in timetable.cards.filter(lesson__teachers=teacher, day__isnull=False) for i in range(c.length)}
        self.assertTrue(busy)
        from timetable.models import Lesson, Period, SchoolClass, Subject, Teacher

        for i in range(6):
            Period.objects.create(school=other, index=i, name=f"{i + 1}")
        same = Teacher.objects.create(school=other, first_name=teacher.first_name, last_name=teacher.last_name)
        cls = SchoolClass.objects.create(school=other, name="G-1")
        lesson = Lesson.objects.create(school=other, subject=Subject.objects.create(school=other, name="Mat"), periods_per_week=2)
        lesson.classes.set([cls])
        lesson.teachers.set([same])
        starts = set(build_problem(other).cards[0].starts)
        self.assertTrue(busy <= starts)  # henüz bağlı değil
        response = self.client.post(reverse("timetable:school_settings", args=[other.pk]), {
            "name": "Gece", "days_per_week": "5", "weeks_count": "1", "terms_count": "1", "linked_programs": [self.school.pk],
            "periods-TOTAL_FORMS": "6", "periods-INITIAL_FORMS": "6", "periods-MIN_NUM_FORMS": "0", "periods-MAX_NUM_FORMS": "1000",
            **{f"periods-{i}-id": p.pk for i, p in enumerate(other.periods.all())},
            **{f"periods-{i}-name": p.name for i, p in enumerate(other.periods.all())},
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn(self.school, other.linked_programs.all())
        starts = set(build_problem(other).cards[0].starts)
        self.assertFalse(busy & starts)  # diğer programdaki dolu saatler kapalı
        self.assertIn(other, self.school.linked_programs.all())  # bağ iki yönlü

    def test_program_delete_requires_name(self):
        other = School.objects.create(name="Silinecek", institution=self.institution)
        url = reverse("timetable:program_delete", args=[other.pk])
        self.client.post(url, {"confirm": "yanlış"})
        self.assertTrue(School.objects.filter(pk=other.pk).exists())
        response = self.client.post(url, {"confirm": "Silinecek"})
        self.assertRedirects(response, reverse("timetable:institution_detail", args=[self.institution.pk]))
        self.assertFalse(School.objects.filter(pk=other.pk).exists())


class ProgramCopyTests(TestCase):
    def test_copy_program_with_all_parts(self):
        from timetable import copying, refs
        from timetable.demo import create_demo_school
        from timetable.models import Availability, LessonRef

        source = create_demo_school()
        timetable = generate_timetable(source, "ilk", time_limit=20)
        School.objects.filter(pk=source.pk).update(active_timetable=timetable)
        source.refresh_from_db()
        refs.auto_number(source, timetable, "1001")
        manager = User.objects.create_user("kopya", password="parola-123456")
        M.objects.create(user=manager, institution=source.institution, permissions=M.ALL)
        self.client.force_login(manager)
        response = self.client.post(reverse("timetable:program_copy", args=[source.institution_id]), {
            "source": source.pk, "name": "2.YY", "parts": list(copying.PARTS),
        })
        copy = School.objects.get(name="2.YY")
        self.assertRedirects(response, reverse("timetable:school_detail", args=[copy.pk]))
        self.assertEqual(copy.institution, source.institution)
        for rel in ("periods", "subjects", "teachers", "classes", "classrooms", "lessons", "relationships", "duty_places"):
            self.assertEqual(getattr(copy, rel).count(), getattr(source, rel).count(), rel)
        self.assertEqual(Availability.objects.filter(school=copy).count(), Availability.objects.filter(school=source).count())
        self.assertEqual(LessonRef.objects.filter(lesson__school=copy).count(), LessonRef.objects.filter(lesson__school=source).count())
        # Kopya kaynakla kayıt paylaşmaz
        self.assertFalse(copy.lessons.filter(teachers__school=source).exists())
        self.assertFalse(copy.lessons.filter(classes__school=source).exists())
        self.assertEqual(sum(g.count() for g in [copy.classes.first().divisions.all()]), source.classes.first().divisions.count())
        placed = copy.timetables.get()
        self.assertEqual(placed.cards.filter(day__isnull=False).count(), timetable.cards.filter(day__isnull=False).count())
        from timetable.services import verify_timetable

        violations, _ = verify_timetable(placed)
        self.assertFalse([v for v in violations if v.level == "hard"])

    def test_dependencies_are_added(self):
        from timetable import copying

        self.assertEqual(copying.resolve({"refler"}), {"refler", "dersler", "ogretmenler", "derslikler", "siniflar"})


class AuditTests(TestCase):
    def setUp(self):
        self.school = build_school()
        self.timetable = generate_timetable(self.school, "ilk", time_limit=10)
        self.manager = User.objects.create_user("denetci", password="parola-123456")
        M.objects.create(user=self.manager, institution=self.school.institution, permissions=M.ALL)

    def test_actions_are_logged_with_details(self):
        from timetable.models import AuditLog

        self.assertTrue(self.client.login(username="denetci", password="parola-123456"))
        self.assertTrue(AuditLog.objects.filter(action="Giriş yaptı", username="denetci").exists())
        self.client.login(username="denetci", password="yanlis")
        self.assertTrue(AuditLog.objects.filter(action="Başarısız giriş denemesi").exists())
        self.client.post(reverse("timetable:api_bulk", args=[self.timetable.pk]), json.dumps({"action": "lock_all"}), content_type="application/json")
        entry = AuditLog.objects.filter(action="Toplu işlem").get()
        self.assertEqual(entry.school, self.school)
        self.assertEqual(entry.institution, self.school.institution)
        self.assertIn("kilitlendi", entry.detail)
        self.client.post(reverse("timetable:data_new", args=[self.school.pk, "ders-adlari"]), {"name": "Felsefe"})
        self.assertIn("Felsefe", AuditLog.objects.filter(action="Kayıt ekledi").get().detail)
        # Yetkisiz (403) istekler değişiklik sayılmaz
        self.client.post(reverse("timetable:central_school_new"), {"school_name": "X"})
        self.assertFalse(AuditLog.objects.filter(action="Kurum oluşturdu").exists())

        page = self.client.get(reverse("timetable:institution_log", args=[self.school.institution_id]) + "?q=toplu")
        self.assertContains(page, "Toplu işlem")
        self.assertNotContains(page, "Kayıt ekledi")
        # Görüntüleme yetkilisi günlüğü göremez
        viewer = User.objects.create_user("bakan", password="parola-123456")
        M.objects.create(user=viewer, institution=self.school.institution, permissions=[])
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(reverse("timetable:institution_log", args=[self.school.institution_id])).status_code, 403)

    def test_program_delete_is_logged_without_dangling_reference(self):
        from timetable.models import AuditLog

        other = School.objects.create(name="Silinecek", institution=self.school.institution)
        self.client.force_login(self.manager)
        self.client.post(reverse("timetable:program_delete", args=[other.pk]), {"confirm": "Silinecek"})
        entry = AuditLog.objects.get(action="Program sildi")
        self.assertIsNone(entry.school)
        self.assertEqual(entry.program_name, "Silinecek")
        self.assertEqual(entry.institution, self.school.institution)


class BackupTests(TestCase):
    def test_backup_create_download_restore(self):
        import gzip
        import json
        import tempfile
        from pathlib import Path

        from django.core.management import call_command
        from django.test import override_settings

        with tempfile.TemporaryDirectory() as tmp, override_settings(BACKUP_DIR=Path(tmp), BACKUP_KEEP=2):
            school = build_school()
            central = User.objects.create_superuser("yedekci", password="parola-123456")
            self.client.force_login(central)
            for _ in range(3):
                self.client.post(reverse("timetable:backups"))
            files = sorted(Path(tmp).iterdir())
            self.assertLessEqual(len(files), 2)  # eskiler silindi
            page = self.client.get(reverse("timetable:backups"))
            self.assertContains(page, files[-1].name)
            response = self.client.get(reverse("timetable:backups") + f"?indir={files[-1].name}")
            data = json.loads(gzip.decompress(b"".join(response.streaming_content)))
            self.assertTrue(any(row["model"] == "timetable.school" and row["fields"]["name"] == school.name for row in data))
            self.assertEqual(self.client.get(reverse("timetable:backups") + "?indir=../settings.py").status_code, 404)
            # Geri yükleme: veriyi silip yedekten dön
            name = school.name
            School.objects.all().delete()
            call_command("loaddata", str(files[-1]), verbosity=0)
            self.assertTrue(School.objects.filter(name=name).exists())
            # Merkez dışı kullanıcı yedeklere erişemez
            user = User.objects.create_user("normal", password="parola-123456")
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse("timetable:backups")).status_code, 403)
