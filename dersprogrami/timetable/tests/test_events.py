"""Etkinlik ve telafi (events.py): uygun saat önerisi, karma grup, çakışma denetimi, sayfa ve takvim."""

import datetime

from django.contrib.auth import get_user_model
User = get_user_model()  # KAMYOSİS: özel kullanıcı modeli
from django.test import TestCase
from django.urls import reverse

from timetable import events, substitutes, teacher_calendar
from timetable.models import (
    Absence,
    Card,
    Classroom,
    Division,
    Event,
    Group,
    Lesson,
    Notification,
    Period,
    School,
    SchoolClass,
    Student,
    Subject,
    Teacher,
    Timetable,
)

MONDAY = datetime.date(2026, 11, 9)  # pazartesi; salı = +1


class EventTests(TestCase):
    """2 gün × 4 saat. A sınıfı: BİL (Ali) pazartesi 1–2; B sınıfı: MAT (Can) pazartesi 3. Derslik Lab, pazartesi
    4. saatte doluyor (FİZ, Ece, C sınıfı)."""

    def setUp(self):
        self.school = School.objects.create(name="MYO", days_per_week=2)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i),
                                  end_time=datetime.time(8 + i, 40))
        self.lab = Classroom.objects.create(school=self.school, name="Lab", capacity=40)
        self.small = Classroom.objects.create(school=self.school, name="Oda", capacity=5)
        self.ali = Teacher.objects.create(school=self.school, first_name="Ali", last_name="Kaya",
                                          user=User.objects.create_user("ali"))
        self.can = Teacher.objects.create(school=self.school, first_name="Can", last_name="Er")
        self.ece = Teacher.objects.create(school=self.school, first_name="Ece", last_name="Su")
        self.a = SchoolClass.objects.create(school=self.school, name="A", student_count=20)
        self.b = SchoolClass.objects.create(school=self.school, name="B", student_count=15)
        self.c = SchoolClass.objects.create(school=self.school, name="C", student_count=10)
        self.tt = Timetable.objects.create(school=self.school, name="P", status=Timetable.OK)
        self.school.active_timetable = self.tt
        self.school.save()
        self.bil = self._lesson("BİL", self.a, self.ali, [(0, 0, 2)])
        self.mat = self._lesson("MAT", self.b, self.can, [(0, 2, 1)])
        self.fiz = self._lesson("FİZ", self.c, self.ece, [(0, 3, 1)], room=self.lab)

    def _lesson(self, name, cls, teacher, cards, room=None):
        lesson = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name=name),
                                       periods_per_week=sum(c[2] for c in cards), card_length=cards[0][2])
        lesson.classes.add(cls)
        lesson.teachers.add(teacher)
        lesson.classrooms.add(self.lab)
        for day, period, length in cards:
            Card.objects.create(timetable=self.tt, lesson=lesson, day=day, period=period, length=length, classroom=room)
        return lesson

    def slots(self, spec, length=1, start=MONDAY, end=MONDAY):
        cal = events.Calendar(self.school)
        return [(s["date"].weekday(), s["period"]) for s in cal.suggest(spec, length, start, end, limit=50, per_day=10)]

    def test_makeup_avoids_teacher_class_and_room(self):
        spec = events.makeup_spec(self.school, [self.bil])
        self.assertEqual(spec.size, 20)
        self.assertEqual(spec.rooms[0], self.lab.pk)
        # Pazartesi 1–2 A ve Ali dolu; 3 ve 4 boş (4'te Lab dolu ama Oda küçük → Lab yok, Oda sığmaz)
        self.assertEqual(self.slots(spec), [(0, 2)])

    def test_mixed_group_of_two_lessons(self):
        spec = events.makeup_spec(self.school, [self.bil, self.mat])
        self.assertEqual(spec.teachers, {self.ali.pk, self.can.pk})
        self.assertEqual(spec.size, 35)
        self.assertEqual(self.slots(spec), [])  # pazartesi 3: B'nin dersi; 4: Lab dolu, Oda küçük
        self.assertEqual(self.slots(spec, start=MONDAY + datetime.timedelta(days=1), end=MONDAY + datetime.timedelta(days=1)),
                         [(1, 0), (1, 1), (1, 2), (1, 3)])

    def test_extra_student_from_another_class_counts(self):
        student = Student.objects.create(school=self.school, number="17", first_name="Deniz", school_class=self.b)
        spec = events.makeup_spec(self.school, [self.bil], extra_students=[student.pk])
        self.assertEqual(spec.size, 21)
        cal = events.Calendar(self.school)
        self.assertTrue(any("Deniz" in c for c in cal.conflicts(MONDAY, [2], spec)))  # B'nin MAT dersi
        self.assertEqual(cal.conflicts(MONDAY, [3], spec), [])

    def test_groups_of_same_division_do_not_block_each_other(self):
        division = Division.objects.create(school_class=self.a, name="Lab")
        g1 = Group.objects.create(division=division, name="G1", student_count=10)
        g2 = Group.objects.create(division=division, name="G2", student_count=10)
        other = Group.objects.create(division=Division.objects.create(school_class=self.a, name="Dil"), name="İng")
        lab = Lesson.objects.create(school=self.school, subject=Subject.objects.create(school=self.school, name="LAB"))
        lab.classes.add(self.a)
        lab.groups.add(g1)
        Card.objects.create(timetable=self.tt, lesson=lab, day=1, period=0, length=1)
        cal = events.Calendar(self.school)
        tuesday = MONDAY + datetime.timedelta(days=1)
        self.assertTrue(cal.conflicts(tuesday, [0], events.Spec(groups={g1.pk})))
        self.assertEqual(cal.conflicts(tuesday, [0], events.Spec(groups={g2.pk})), [])
        self.assertTrue(cal.conflicts(tuesday, [0], events.Spec(groups={other.pk})))  # öğrencileri bilinmiyor
        self.assertTrue(cal.conflicts(tuesday, [0], events.Spec(classes={self.a.pk})))

    def test_absence_and_other_event_block(self):
        tuesday = MONDAY + datetime.timedelta(days=1)
        Absence.objects.create(school=self.school, date=tuesday, teacher=self.ali, periods=[0])
        meeting = Event.objects.create(school=self.school, title="Toplantı", date=tuesday, period=1, length=1)
        meeting.classrooms.add(self.lab)
        cal = events.Calendar(self.school)
        spec = events.makeup_spec(self.school, [self.bil])
        self.assertIn("devamsız", cal.conflicts(tuesday, [0], spec)[0])
        self.assertEqual(cal.conflicts(tuesday, [1], spec), [])  # Ali boş; Lab'ı derslik denetimi ayrıca yapar
        self.assertIn("Toplantı", cal.conflicts(tuesday, [1], spec, rooms=[self.lab.pk])[0])
        self.assertNotIn(self.lab, cal.free_rooms(tuesday, [1]))

    def test_page_suggest_save_and_calendar(self):
        admin = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.client.force_login(admin)
        url = reverse("timetable:events", args=[self.school.pk])
        tuesday = MONDAY + datetime.timedelta(days=1)
        page = self.client.get(url, {"action": "suggest", "ders": [self.bil.pk, self.mat.pk], "ilk": tuesday.isoformat(),
                                     "son": tuesday.isoformat(), "telafi_tarihi": MONDAY.isoformat()})
        self.assertEqual(len(page.context["suggestions"]), 3)  # günde en çok 3 seçenek
        self.assertContains(page, "Uygun saatler")
        response = self.client.post(url, {"action": "save_makeup", "ders": [self.bil.pk, self.mat.pk], "tarih": tuesday.isoformat(),
                                          "saat": "1", "derslik": self.lab.pk, "telafi_tarihi": MONDAY.isoformat()})
        self.assertEqual(response.status_code, 302)
        event = Event.objects.get()
        self.assertEqual((event.kind, event.period, event.length), (Event.MAKEUP, 1, 2))  # BİL kartı 2 saatlik
        self.assertEqual(set(event.classes.all()), {self.a, self.b})
        self.assertEqual(event.missed_date, MONDAY)
        self.assertTrue(Notification.objects.filter(user=self.ali.user, title__startswith="Telafi dersi").exists())
        # Aynı saat ikinci kez kaydedilemez
        self.client.post(url, {"action": "save_makeup", "ders": [self.bil.pk], "tarih": tuesday.isoformat(), "saat": "1",
                               "derslik": self.lab.pk})
        self.assertEqual(Event.objects.count(), 1)
        # Öğretmenin takvimi ve vekâlet adayları
        items = teacher_calendar.events(self.ali, tuesday, tuesday + datetime.timedelta(days=1))
        self.assertEqual([e["kind"] for e in items], ["telafi"])
        listing = self.client.get(url, {"baslangic": tuesday.isoformat()})
        self.assertContains(listing, "Telafi: BİL, MAT")

    def test_reservation_conflict_needs_confirmation(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@x.tr", "pw"))
        url = reverse("timetable:events", args=[self.school.pk])
        data = {"action": "reserve", "r_baslik": "Seminer", "r_tarih": MONDAY.isoformat(), "r_saat": "3", "r_sure": "1",
                "r_derslik": [self.lab.pk]}
        page = self.client.post(url, data)
        self.assertEqual(Event.objects.count(), 0)
        self.assertIn("4. saat: Lab dolu – FİZ", page.context["reserve_conflicts"])
        self.client.post(url, {**data, "zorla": "1"})
        self.assertEqual(Event.objects.get().title, "Seminer")
        free = self.client.post(url, {**data, "action": "free_rooms"}).context["free_rooms"]
        self.assertEqual(free, [self.small])

    def test_teacher_in_event_is_not_offered_as_substitute(self):
        Absence.objects.create(school=self.school, date=MONDAY, teacher=self.ece)  # FİZ pazartesi 4. saat boşta
        before = substitutes.day_plan(self.school, self.tt, MONDAY)[0]["slots"][0]["candidates"]
        self.assertIn(self.ali.pk, [c["teacher"].pk for c in before])
        meeting = Event.objects.create(school=self.school, title="Kurul", date=MONDAY, period=3, length=1)
        meeting.teachers.add(self.ali)
        after = substitutes.day_plan(self.school, self.tt, MONDAY)[0]["slots"][0]["candidates"]
        self.assertNotIn(self.ali.pk, [c["teacher"].pk for c in after])

    def test_weekend_option_and_blocker_summary(self):
        from collections import Counter

        saturday = MONDAY + datetime.timedelta(days=5)
        spec = events.makeup_spec(self.school, [self.bil, self.mat])
        cal = events.Calendar(self.school)
        blockers = Counter()
        self.assertEqual(cal.suggest(spec, 1, MONDAY, MONDAY, blockers=blockers), [])
        self.assertEqual(blockers["A"], 2)  # BİL: pazartesi 1–2
        self.assertEqual(cal.suggest(spec, 1, saturday, saturday), [])  # ders günü değil
        weekend = cal.suggest(spec, 1, saturday, saturday, weekend=True)
        self.assertEqual([s["day_name"] for s in weekend], ["Cumartesi"] * 3)
