"""Bölüm veri girişi: bölüm sorumlusu ders–öğretmen kısım dağılımını ve mazeretleri girer, program sorumlusu onaylar."""

import datetime

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import departments
from timetable.models import (AvailabilityRequest, Department, DepartmentSubmission as DS, Institution, Lesson, Membership, Period,
                              School, SchoolClass, Subject, Teacher, TeacherQuota)


class DepartmentTests(TestCase):
    def setUp(self):
        inst = Institution.objects.create(name="Kurum")
        self.school = School.objects.create(name="MYO", institution=inst, days_per_week=5)
        for i in range(4):
            Period.objects.create(school=self.school, index=i, name=str(i + 1), start_time=datetime.time(8 + i), end_time=datetime.time(8 + i, 40))
        self.ahmet = Teacher.objects.create(school=self.school, first_name="Ahmet", last_name="Kaya", short="SVN Ahmet KAYA")
        self.mehmet = Teacher.objects.create(school=self.school, first_name="Mehmet", last_name="Er", short="SVN Mehmet ER")
        self.other = Teacher.objects.create(school=self.school, first_name="Ayşe", last_name="Dil", short="YDL Ayşe DİL")
        self.svn = Subject.objects.create(school=self.school, name="Savunma", short="SVN211")
        Subject.objects.create(school=self.school, name="İngilizce", short="YDL101")
        for i in range(4):
            lesson = Lesson.objects.create(school=self.school, subject=self.svn, periods_per_week=2)
            lesson.classes.add(SchoolClass.objects.create(school=self.school, name=f"{i + 1}.KISIM"))
            lesson.teachers.add(self.ahmet)
        self.admin = User.objects.create_superuser("admin", "a@x.tr", "pw")
        self.head = User.objects.create_user("bolum", password="pw")
        self.ahmet.user = self.head
        self.ahmet.save()

    def test_suggest_create_submit_approve(self):
        self.client.force_login(self.admin)
        url = reverse("timetable:departments", args=[self.school.pk])
        names = [s["name"] for s in departments.suggestions(self.school)]
        self.assertEqual(names, ["SVN", "YDL"])
        self.client.post(url, {"action": "suggest", "oneri": ["SVN"]})
        dept = Department.objects.get(name="SVN")
        self.assertEqual(set(dept.teachers.all()), {self.ahmet, self.mehmet})
        self.client.post(url, {"action": "save", "bolum": dept.pk, "name": "Savunma Bölümü", "subjects": [self.svn.pk],
                               "teachers": [self.ahmet.pk, self.mehmet.pk], "heads": [self.ahmet.pk]})
        self.assertEqual(list(Department.objects.get(pk=dept.pk).users.all()), [self.head])

        # bölüm sorumlusu: yalnızca bölüm ekranı
        self.client.force_login(self.head)
        self.assertRedirects(self.client.get(reverse("timetable:school_list")), reverse("timetable:department_portal", args=[dept.pk]),
                             fetch_redirect_response=False)
        portal = reverse("timetable:department_portal", args=[dept.pk])
        page = self.client.get(portal)
        self.assertContains(page, "4 kısım × 2 saat")
        self.assertEqual(self.client.get(reverse("timetable:school_detail", args=[self.school.pk])).status_code, 403)
        self.client.post(portal, {"action": "submit", f"t-{self.svn.pk}": [self.ahmet.pk, self.mehmet.pk], f"n-{self.svn.pk}": ["1", "3"],
                                  "message": "Mehmet Bey ağırlıklı girsin"})
        sub = DS.objects.get(department=dept)
        self.assertEqual((sub.status, sub.quotas), (DS.PENDING, {str(self.svn.pk): {str(self.ahmet.pk): 1, str(self.mehmet.pk): 3}}))
        self.client.post(portal, {"action": "draft", f"t-{self.svn.pk}": [self.ahmet.pk], f"n-{self.svn.pk}": ["4"]})
        self.assertEqual(DS.objects.get(pk=sub.pk).status, DS.PENDING)  # bekleyen öneri geri çekilmeden değişmez

        # program sorumlusu onaylar: kota + ön dağıtım
        self.client.force_login(self.admin)
        review = self.client.get(url + f"?bolum={dept.pk}")
        self.assertContains(review, "Mehmet Bey ağırlıklı girsin")
        self.assertContains(review, "Mehmet Er: 0 → ")
        self.client.post(url, {"action": "approve", "oneri": sub.pk, "dagit": "1", "reply": "Uygun"})
        self.assertEqual(DS.objects.get(pk=sub.pk).status, DS.APPROVED)
        self.assertEqual(dict(TeacherQuota.objects.filter(subject=self.svn).values_list("teacher_id", "count")), {self.ahmet.pk: 1, self.mehmet.pk: 3})
        counts = {t.pk: Lesson.objects.filter(subject=self.svn, teachers=t).count() for t in (self.ahmet, self.mehmet)}
        self.assertEqual(counts, {self.ahmet.pk: 1, self.mehmet.pk: 3})

    def test_excuse_goes_to_teacher_requests_and_access_is_limited(self):
        dept = Department.objects.create(school=self.school, name="SVN")
        dept.teachers.set([self.ahmet, self.mehmet])
        dept.users.set([self.head])
        portal = reverse("timetable:department_portal", args=[dept.pk])
        self.client.force_login(self.head)
        self.client.post(portal, {"sekme": "mazeret", "ogretmen": self.mehmet.pk, "h-1-2": "no", "reason": "Lisansüstü dersi"})
        req = AvailabilityRequest.objects.get(teacher=self.mehmet)
        self.assertEqual((req.changes, req.requested_by), ([[1, 2, "no"]], self.head))
        self.assertEqual(self.client.post(portal, {"sekme": "mazeret", "ogretmen": self.other.pk, "h-1-2": "no"}).status_code, 404)
        stranger = User.objects.create_user("baska", password="pw")
        Membership.objects.create(user=stranger, institution=self.school.institution, permissions=[Membership.VIEW])
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(portal).status_code, 404)
