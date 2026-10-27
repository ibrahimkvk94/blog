"""aSc TimeTables 2012 XML dışa aktarım biçimiyle içe aktarma (gerçek dosyanın yapısını taklit eder)."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from timetable import asc_xml
from timetable.models import Classroom, SchoolClass, Teacher
from timetable.services import check_school, verify_timetable

SAMPLE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<timetable importtype="database" options="export:idprefix:%CHRID,import:idprefix:%TEMPID,groupstype1,decimalseparatordot" displayname="aSc Timetables 2012 XML">
  <periods options="canadd,export:silent" columns="period,name,short,starttime,endtime">
    <period name="1" short="1" period="1" starttime="8:20" endtime="9:00"/>
    <period name="2" short="2" period="2" starttime="9:10" endtime="9:50"/>
    <period name="3" short="3" period="3" starttime="10:00" endtime="10:40"/>
    <period name="4" short="4" period="4" starttime="10:50" endtime="11:30"/>
  </periods>
  <breaks options="canadd,export:silent" columns="break,name,short,starttime,endtime"/>
  <daysdefs options="canadd,export:silent" columns="id,days,name,short">
    <daysdef id="D1" name="Pazartesi" short="Pa" days="10000"/>
    <daysdef id="DX" name="Herhangi Bir Gün" short="X" days="10000,01000,00100,00010,00001"/>
    <daysdef id="DE" name="Her Gün" short="E" days="11111"/>
  </daysdefs>
  <weeksdefs options="canadd,export:silent" columns="id,weeks,name,short">
    <weeksdef id="W" name="Tüm Haftalar" short="Tümü" weeks="1"/>
  </weeksdefs>
  <termsdefs options="canadd,export:silent" columns="id,terms,name,short">
    <termsdef id="Y" name="Bütün Bir yıl" short="YIL" terms="1"/>
  </termsdefs>
  <subjects options="canadd,export:silent,customfield1:#3375" columns="id,name,short,partner_id,customfield1">
    <subject id="S1" name="Beden Eğitimi" short="TBE201" partner_id="" customfield1="2"/>
    <subject id="S2" name="Yabancı Dil" short="YDL201" partner_id="" customfield1="1"/>
  </subjects>
  <teachers options="canadd,export:silent" columns="id,name,short,gender,color,email,mobile,partner_id,firstname,lastname">
    <teacher id="T1" firstname="Durmuş Faruk" lastname="AKSANOĞULLARI" name="Durmuş Faruk AKSANOĞULLARI" short="BES Durmuş Faruk AKSANOĞULLARI" gender="" color="#FFFFFF" email="" mobile="" partner_id=""/>
    <teacher id="T2" firstname="Ayşe" lastname="KAYA" name="Ayşe KAYA" short="YDL Ayşe KAYA" gender="" color="#FF9966" email="" mobile="" partner_id=""/>
    <teacher id="T3" firstname="Can" lastname="DEMİR" name="Can DEMİR" short="BES Can DEMİR" gender="" color="#FF9966" email="" mobile="" partner_id=""/>
  </teachers>
  <buildings options="canadd,export:silent" columns="id,name,partner_id"/>
  <classrooms options="canadd,export:silent" columns="id,name,short,capacity,buildingid,partner_id">
    <classroom id="R1" name="Spor Salonu 1" short="Spor Salonu 1" capacity="*" buildingid="" partner_id=""/>
    <classroom id="R2" name="YDL-BDDL 1" short="YDL-BDDL 1" capacity="*" buildingid="" partner_id=""/>
  </classrooms>
  <grades options="canadd,export:silent" columns="grade,name,short">
    <grade name="Sınıf 1" short="S 1" grade="1"/>
  </grades>
  <classes options="canadd,export:silent" columns="id,name,short,classroomids,teacherid,grade,partner_id">
    <class id="C10" name="10.KISIM" short="10MKT" teacherid="" classroomids="" grade="" partner_id=""/>
    <class id="C2" name="2.KISIM" short="2SVN" teacherid="T2" classroomids="" grade="" partner_id=""/>
  </classes>
  <groups options="canadd,export:silent" columns="id,classid,name,entireclass,divisiontag,studentcount,studentids">
    <group id="G2" name="Bütün Sınıf" classid="C2" studentids="" entireclass="1" divisiontag="0"/>
    <group id="G2a" name="Grup 1" classid="C2" studentids="" entireclass="0" divisiontag="1"/>
    <group id="G2b" name="Grup 2" classid="C2" studentids="" entireclass="0" divisiontag="1"/>
    <group id="G10" name="Bütün Sınıf" classid="C10" studentids="" entireclass="1" divisiontag="0"/>
  </groups>
  <students options="canadd,export:silent" columns="id,classid,name,number,email,mobile,partner_id,firstname,lastname"/>
  <studentsubjects options="canadd,export:silent" columns="studentid,subjectid,seminargroup,importance,alternatefor"/>
  <lessons options="canadd,export:silent" columns="id,subjectid,classids,groupids,teacherids,classroomids,periodspercard,periodsperweek,daysdefid,weeksdefid,termsdefid,seminargroup,capacity,partner_id">
    <lesson id="L1" classids="C2" subjectid="S1" periodspercard="2" periodsperweek="2.0" teacherids="T1" classroomids="R1" groupids="G2" seminargroup="" termsdefid="Y" weeksdefid="W" daysdefid="DX" capacity="*" partner_id=""/>
    <lesson id="L2" classids="C10" subjectid="S1" periodspercard="2" periodsperweek="2.0" teacherids="T3" classroomids="R1" groupids="G10" seminargroup="" termsdefid="Y" weeksdefid="W" daysdefid="DX" capacity="*" partner_id=""/>
    <lesson id="L3" classids="C2" subjectid="S2" periodspercard="1" periodsperweek="1.0" teacherids="T2" classroomids="R2" groupids="G2a" seminargroup="" termsdefid="Y" weeksdefid="W" daysdefid="D1" capacity="*" partner_id=""/>
  </lessons>
  <cards options="canadd,export:silent" columns="lessonid,period,days,weeks,terms,classroomids">
    <card lessonid="L1" classroomids="R1" period="1" weeks="1" terms="1" days="10000"/>
    <card lessonid="L1" classroomids="R1" period="2" weeks="1" terms="1" days="10000"/>
    <card lessonid="L2" classroomids="R1" period="1" weeks="1" terms="1" days="10000"/>
    <card lessonid="L2" classroomids="R1" period="2" weeks="1" terms="1" days="10000"/>
    <card lessonid="L3" classroomids="R2" period="4" weeks="1" terms="1" days="10000"/>
  </cards>
  <classroomsupervisions options="canadd,export:silent" columns="classroomid,teacherid,day,week,term,period,break"/>
</timetable>
""".encode()


class AscExportImportTests(TestCase):
    def test_import_aSc_2012_export(self):
        school, timetable = asc_xml.import_school(SAMPLE, name="asc")
        self.assertEqual(school.periods.count(), 4)
        self.assertEqual([c.short for c in school.classes.all()], ["2SVN", "10MKT"])  # doğal sıra
        cls = SchoolClass.objects.get(school=school, short="2SVN")
        self.assertEqual(cls.name, "2.KISIM")
        self.assertEqual(cls.class_teacher.last_name, "KAYA")
        self.assertEqual([d.name for d in cls.divisions.all()], ["Grup 1 / Grup 2"])
        teacher = Teacher.objects.get(school=school, last_name="AKSANOĞULLARI")
        self.assertEqual(teacher.short, "BES Durmuş Faruk AKSANOĞULLARI")
        gym = Classroom.objects.get(school=school, name="Spor Salonu 1")
        self.assertEqual(gym.max_lessons, 2)  # kartlarda iki ders aynı anda salonda
        self.assertIsNone(gym.capacity)

        cards = timetable.cards.all()
        self.assertEqual(sorted((c.day, c.period, c.length) for c in cards), [(0, 0, 2), (0, 0, 2), (0, 3, 1)])
        violations, stats = verify_timetable(timetable)
        self.assertEqual(violations, [])
        self.assertEqual(stats["unplaced"], 0)
        self.assertFalse([i for i in check_school(school) if i.level == "error"])

        # Pazartesi'ye bağlı ders yalnızca Pazartesi'ye konabilir (daysdef).
        lesson = school.lessons.get(subject__short="YDL201")
        self.assertEqual(lesson.availabilities.count(), 4 * 4)

    def test_import_view_opens_timetable(self):
        user = User.objects.create_superuser("asc", password="parola-123456")
        self.client.force_login(user)
        from django.core.files.uploadedfile import SimpleUploadedFile

        response = self.client.post(reverse("timetable:import_asc"), {"file": SimpleUploadedFile("okul.xml", SAMPLE)})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/program/", response["Location"])
        grid = self.client.get(response["Location"].replace("/program/", "/api/program/") + "izgara/").json()
        self.assertEqual([r["label"] for r in grid["rows"]], ["2SVN", "10MKT"])
        self.assertEqual(grid["violations"], [])
