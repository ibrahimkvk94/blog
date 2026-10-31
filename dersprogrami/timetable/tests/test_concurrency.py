"""Eşzamanlı düzenleme koruması: program sürümü ve çakışma yanıtı, kim düzenliyor listesi, kayıt formlarında
"siz düzenlerken değişti" uyarısı."""

import json
import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from timetable import concurrency
from timetable.forms import TeacherForm
from timetable.models import AuditLog, Card, EditPresence, Lesson, Period, School, SchoolClass, Subject, Teacher, Timetable


def build_program():
    school = School.objects.create(name="Eşzamanlı okul", days_per_week=5)
    for i in range(6):
        Period.objects.create(school=school, index=i, name=f"{i + 1}. saat")
    cls = SchoolClass.objects.create(school=school, name="9-A")
    cards = {}
    for row, name in enumerate(["Matematik", "Türkçe"]):
        teacher = Teacher.objects.create(school=school, first_name=f"Öğretmen{row}", last_name="Test")
        subject = Subject.objects.create(school=school, name=name)
        lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=3, card_length=1)
        lesson.classes.set([cls])
        lesson.teachers.set([teacher])
        cards[name] = lesson
    timetable = Timetable.objects.create(school=school, name="Program", status=Timetable.OK)
    placed = {}
    for row, (name, lesson) in enumerate(cards.items()):
        for day in range(3):
            placed[(name, day)] = Card.objects.create(timetable=timetable, lesson=lesson, length=1, day=day, period=row)
    return school, timetable, placed


class ProgramRevisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ahmet = User.objects.create_superuser("ahmet", password="parola-123456", first_name="Ahmet", last_name="Yılmaz")
        cls.ayse = User.objects.create_superuser("ayse", password="parola-123456", first_name="Ayşe", last_name="Kaya")

    def setUp(self):
        self.school, self.timetable, self.cards = build_program()
        self.a = self.client
        self.b = self.client_class()
        self.a.force_login(self.ahmet)
        self.b.force_login(self.ayse)

    def revision(self):
        return self.a.get(reverse("timetable:api_grid", args=[self.timetable.pk])).json()["revision"]

    def move(self, client, card, day, period, revision=None, mode="displace", tab="t"):
        headers = {"HTTP_X_EDITOR_TAB": tab}
        if revision is not None:
            headers["HTTP_X_TIMETABLE_REVISION"] = str(revision)
        return client.post(reverse("timetable:api_card_move", args=[card.pk]), json.dumps({"day": day, "period": period, "mode": mode}),
                           content_type="application/json", **headers)

    def test_move_bumps_revision_and_records_who(self):
        r0 = self.revision()
        card = self.cards[("Matematik", 0)]
        res = self.move(self.a, card, 3, 0, r0)
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["revision"], r0 + 1)
        self.assertNotIn("others", data)
        self.timetable.refresh_from_db()
        self.assertEqual(self.timetable.revision, r0 + 1)
        last = self.timetable.changes[-1]
        self.assertEqual((last["user"], last["rev"]), ("Ahmet Y.", r0 + 1))
        self.assertIn(card.pk, last["cards"])

    def test_without_header_behaves_as_before(self):
        res = self.move(self.a, self.cards[("Matematik", 0)], 3, 0)
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("revision", res.json())

    def test_stale_move_of_changed_card_is_rejected(self):
        r0 = self.revision()
        card = self.cards[("Matematik", 0)]
        self.assertEqual(self.move(self.b, card, 3, 0, r0, tab="b").status_code, 200)
        res = self.move(self.a, card, 4, 0, r0, tab="a")
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertTrue(data["stale"])
        self.assertEqual(data["message"], "Bu programı Ayşe K. değiştirdi; görünüm yenilendi.")
        self.assertIn(card.pk, data["cards"])
        card.refresh_from_db()
        self.assertEqual((card.day, card.period), (3, 0))  # Ayşe'nin taşıması korunur

    def test_stale_move_onto_changed_card_is_rejected(self):
        r0 = self.revision()
        math = self.cards[("Matematik", 0)]
        self.move(self.b, math, 3, 0, r0, tab="b")
        turkish = self.cards[("Türkçe", 0)]
        res = self.move(self.a, turkish, 3, 0, r0, tab="a")  # Ayşe'nin yeni koyduğu kartı yerinden çıkarırdı
        self.assertEqual(res.status_code, 409)
        math.refresh_from_db()
        turkish.refresh_from_db()
        self.assertEqual((math.day, math.period), (3, 0))
        self.assertEqual((turkish.day, turkish.period), (0, 1))

    def test_stale_but_unrelated_move_is_applied_and_reported(self):
        r0 = self.revision()
        self.move(self.b, self.cards[("Matematik", 0)], 3, 0, r0, tab="b")
        turkish = self.cards[("Türkçe", 1)]
        res = self.move(self.a, turkish, 4, 2, r0, tab="a")
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["revision"], r0 + 2)
        self.assertIn("Ayşe K.", data["others"])
        turkish.refresh_from_db()
        self.assertEqual((turkish.day, turkish.period), (4, 2))

    def test_same_tab_requests_are_not_conflicts(self):
        r0 = self.revision()
        self.move(self.a, self.cards[("Matematik", 0)], 3, 0, r0, tab="a")
        res = self.move(self.a, self.cards[("Matematik", 0)], 4, 0, r0, tab="a")  # yanıtı henüz gelmemiş işlem
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("others", res.json())

    def test_own_other_tab_message(self):
        r0 = self.revision()
        self.move(self.a, self.cards[("Matematik", 0)], 3, 0, r0, tab="a1")
        res = self.move(self.a, self.cards[("Matematik", 0)], 4, 0, r0, tab="a2")
        self.assertEqual(res.status_code, 409)
        self.assertIn("başka bir sekmede", res.json()["message"])

    def test_program_wide_actions_need_fresh_revision(self):
        r0 = self.revision()
        self.move(self.b, self.cards[("Matematik", 0)], 3, 0, r0, tab="b")
        headers = {"HTTP_X_TIMETABLE_REVISION": str(r0), "HTTP_X_EDITOR_TAB": "a"}
        undo = self.a.post(reverse("timetable:api_undo", args=[self.timetable.pk]), **headers)
        self.assertEqual(undo.status_code, 409)  # Ayşe'nin işlemini geri almaz
        bulk = self.a.post(reverse("timetable:api_bulk", args=[self.timetable.pk]), json.dumps({"action": "lock_all"}),
                           content_type="application/json", **headers)
        self.assertEqual(bulk.status_code, 409)
        self.assertFalse(Card.objects.filter(timetable=self.timetable, locked=True).exists())
        fresh = {"HTTP_X_TIMETABLE_REVISION": str(r0 + 1), "HTTP_X_EDITOR_TAB": "a"}
        undo = self.a.post(reverse("timetable:api_undo", args=[self.timetable.pk]), **fresh)
        self.assertEqual(undo.status_code, 200)
        self.assertEqual(undo.json()["revision"], r0 + 2)  # geri al da sürümü artırır

    def test_truncated_log_rejects(self):
        Timetable.objects.filter(pk=self.timetable.pk).update(revision=100, changes=[])
        res = self.move(self.a, self.cards[("Matematik", 0)], 3, 0, 50, tab="a")
        self.assertEqual(res.status_code, 409)


class PresenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ahmet = User.objects.create_superuser("ahmet", password="parola-123456", first_name="Ahmet", last_name="Yılmaz")
        cls.ayse = User.objects.create_superuser("ayse", password="parola-123456", first_name="Ayşe", last_name="Kaya")
        cls.murat = User.objects.create_superuser("murat", password="parola-123456", first_name="Murat", last_name="Işık")

    def setUp(self):
        self.school, self.timetable, self.cards = build_program()
        self.url = reverse("timetable:api_presence", args=[self.school.pk])
        self.key = f"program:{self.timetable.pk}"

    def beat(self, user, **body):
        client = self.client_class()
        client.force_login(user)
        return client.post(self.url, json.dumps({"key": self.key, "editing": True, **body}), content_type="application/json")

    def test_lists_others_but_not_self(self):
        self.beat(self.ayse)
        data = self.beat(self.ahmet).json()
        self.assertEqual(data["others"], ["Ayşe K."])
        self.assertEqual(data["text"], "Ayşe K. de bu programı düzenliyor")
        self.assertEqual(self.beat(self.ayse).json()["others"], ["Ahmet Y."])

    def test_stale_and_viewers_are_hidden_and_old_rows_removed(self):
        self.beat(self.ayse)
        self.beat(self.murat, editing=False)  # yalnızca bakıyor
        EditPresence.objects.filter(user=self.ayse).update(last_seen=timezone.now() - timedelta(minutes=3))
        self.assertEqual(self.beat(self.ahmet).json()["others"], [])
        EditPresence.objects.filter(user=self.ayse).update(last_seen=timezone.now() - timedelta(minutes=30))
        self.beat(self.ahmet)
        self.assertFalse(EditPresence.objects.filter(user=self.ayse).exists())

    def test_leave_and_validation(self):
        self.beat(self.ayse)
        client = self.client_class()
        client.force_login(self.ayse)
        client.post(self.url, {"key": self.key, "leave": "1"})  # sendBeacon: form verisi
        self.assertFalse(EditPresence.objects.filter(user=self.ayse).exists())
        self.assertEqual(self.beat(self.ahmet, key="baska:1").status_code, 400)
        other, _, _ = build_program()
        foreign = Timetable.objects.create(school=other, name="Başka")
        self.assertEqual(self.beat(self.ahmet, key=f"program:{foreign.pk}").status_code, 404)

    def test_heartbeat_reports_foreign_change_and_is_not_audited(self):
        seen = Timetable.objects.get(pk=self.timetable.pk).revision
        client = self.client_class()
        client.force_login(self.ayse)
        client.post(reverse("timetable:api_card_move", args=[self.cards[("Matematik", 0)].pk]),
                    json.dumps({"day": 3, "period": 0}), content_type="application/json", HTTP_X_EDITOR_TAB="b")
        data = self.beat(self.ahmet, since=seen, tab="a").json()
        self.assertEqual(data["changed"], "Bu programı Ayşe K. değiştirdi; görünüm yenilendi.")
        self.assertEqual(data["revision"], seen + 1)
        self.assertNotIn("changed", self.beat(self.ahmet, since=seen + 1, tab="a").json())
        self.assertFalse(AuditLog.objects.filter(path=self.url).exists())

    def test_editor_page_has_presence_pill(self):
        client = self.client_class()
        client.force_login(self.ahmet)
        self.assertContains(client.get(reverse("timetable:timetable_detail", args=[self.timetable.pk])), "data-presence")

    def test_names_and_vowel_harmony(self):
        self.assertEqual(concurrency.short_name(self.murat), "Murat I.")
        self.assertEqual(concurrency.presence_text(["Murat"], "programı"), "Murat da bu programı düzenliyor")
        self.assertEqual(concurrency.presence_text(["Ali A."], "kaydı"), "Ali A. da bu kaydı düzenliyor")
        self.assertEqual(concurrency.presence_text(["Ali", "Ayşe K."], "kaydı"), "Ali ve Ayşe K. de bu kaydı düzenliyor")
        self.assertEqual(concurrency.presence_text(["A", "B", "C", "D"], "programı"), "A, B ve 2 kişi daha bu programı düzenliyor")


def form_data(teacher, **changes):
    form = TeacherForm(instance=teacher, school=teacher.school)
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is None or value is False:
            continue
        data[name] = [str(v) for v in value] if isinstance(value, (list, tuple)) else ("on" if value is True else str(value))
    data.update(changes)
    return data


class RecordConflictTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ahmet = User.objects.create_superuser("ahmet", password="parola-123456", first_name="Ahmet", last_name="Yılmaz")
        cls.ayse = User.objects.create_superuser("ayse", password="parola-123456", first_name="Ayşe", last_name="Kaya")

    def setUp(self):
        self.school = School.objects.create(name="Kayıt okulu", days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=f"{i + 1}. saat")
        self.teacher = Teacher.objects.create(school=self.school, first_name="Veli", last_name="Demir", short="VD")
        self.url = reverse("timetable:data_edit", args=[self.school.pk, "ogretmenler", self.teacher.pk])
        self.a, self.b = self.client_class(), self.client_class()
        self.a.force_login(self.ahmet)
        self.b.force_login(self.ayse)

    def token(self, client):
        page = client.get(self.url).content.decode()
        match = re.search(r'name="_kayit_durumu" value="([^"]+)"', page)
        self.assertIsNotNone(match)
        import html

        return html.unescape(match.group(1))

    def save(self, client, token, fetch=True, **changes):
        data = form_data(Teacher.objects.get(pk=self.teacher.pk) if not changes.pop("_stale", False) else self.teacher, **changes)
        data["_kayit_durumu"] = token
        extra = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return client.post(self.url, data, **extra)

    def test_conflict_is_reported_and_not_saved(self):
        token_a, token_b = self.token(self.a), self.token(self.b)
        res = self.save(self.b, token_b, first_name="Velican")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["state"])
        res = self.save(self.a, token_a, _stale=True, first_name="Ali")  # Ahmet eski haliyle açmıştı
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertTrue(data["conflict"])
        self.assertIn("Ayşe K. tarafından", data["message"])
        self.assertIn("Velican", data["html"])
        self.assertIn("Ali", data["html"])
        self.assertIn("Yine de kaydet", data["html"])
        self.assertEqual(Teacher.objects.get(pk=self.teacher.pk).first_name, "Velican")
        res = self.save(self.a, token_a, _stale=True, first_name="Ali", _yine_de="1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(Teacher.objects.get(pk=self.teacher.pk).first_name, "Ali")

    def test_untouched_change_by_other_still_warns_for_stale_values(self):
        token_a, token_b = self.token(self.a), self.token(self.b)
        self.save(self.b, token_b, short="VDM")
        res = self.save(self.a, token_a, _stale=True, last_name="Demirci")  # eski "VD" kısaltmasını geri yazardı
        self.assertEqual(res.status_code, 409)
        self.assertIn("VDM", res.json()["html"])

    def test_same_value_or_fresh_token_is_not_a_conflict(self):
        token_a, token_b = self.token(self.a), self.token(self.b)
        self.save(self.b, token_b, first_name="Velican")
        res = self.save(self.a, token_a, first_name="Velican")  # aynı değer: kaydedilir
        self.assertEqual(res.status_code, 200)
        state = res.json()["state"]
        res = self.save(self.a, state, first_name="Veli")  # kaydetten sonraki belirteçle yeniden kaydetme
        self.assertEqual(res.status_code, 200)

    def test_availability_conflict(self):
        token_a, token_b = self.token(self.a), self.token(self.b)
        self.save(self.b, token_b, availability=json.dumps({"0-0": "no"}))
        res = self.save(self.a, token_a, availability=json.dumps({"1-1": "no"}))
        self.assertEqual(res.status_code, 409)
        self.assertIn("Müsaitlik", res.json()["html"])

    def test_plain_post_rerenders_with_warning(self):
        token_a, token_b = self.token(self.a), self.token(self.b)
        self.save(self.b, token_b, first_name="Velican")
        res = self.save(self.a, token_a, fetch=False, _stale=True, first_name="Ali")
        self.assertContains(res, "siz düzenlerken", status_code=409)
        self.assertContains(res, "Yine de kaydet", status_code=409)
        self.assertContains(res, 'value="Ali"', status_code=409)
        self.assertEqual(Teacher.objects.get(pk=self.teacher.pk).first_name, "Velican")

    def test_record_page_has_presence(self):
        self.assertContains(self.a.get(self.url), f'data-key="kayit:ogretmenler:{self.teacher.pk}"')
