"""Örnek bir lise verisi: 4 şube, bölünmeli seçmeli dersler, birleşik dersler, laboratuvarlar."""

import datetime

from django.db import transaction

from .models import (
    Availability,
    Classroom,
    Division,
    Group,
    Lesson,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
)

SUBJECTS = {
    "TDE": ("Türk Dili ve Edebiyatı", "#fde2e4"),
    "MAT": ("Matematik", "#dfe7fd"),
    "FİZ": ("Fizik", "#e2ece9"),
    "KİM": ("Kimya", "#fff1e6"),
    "BİY": ("Biyoloji", "#e9f5db"),
    "TAR": ("Tarih", "#f0efeb"),
    "COĞ": ("Coğrafya", "#ddedea"),
    "İNG": ("İngilizce", "#cddafd"),
    "BED": ("Beden Eğitimi", "#fad2e1"),
    "DİN": ("Din Kültürü", "#eae4e9"),
    "REH": ("Rehberlik", "#fff1c1"),
    "MÜZ": ("Müzik", "#bee1e6"),
    "ALM": ("Almanca", "#e2cfc4"),
    "FRA": ("Fransızca", "#c5dedd"),
}

TEACHERS = [
    ("Ayşe", "Yılmaz", "AYI"),
    ("Mehmet", "Demir", "MDE"),
    ("Zeynep", "Kaya", "ZKA"),
    ("Ali", "Çelik", "ACE"),
    ("Elif", "Şahin", "EŞA"),
    ("Can", "Aydın", "CAY"),
    ("Deniz", "Öztürk", "DÖZ"),
    ("Selin", "Arslan", "SAR"),
    ("Burak", "Doğan", "BDO"),
    ("Merve", "Kılıç", "MKI"),
    ("Emre", "Koç", "EKO"),
    ("Esra", "Kurt", "EKU"),
    ("Hakan", "Özdemir", "HÖZ"),
    ("Gizem", "Aksoy", "GAK"),
    ("Murat", "Polat", "MPO"),
]


@transaction.atomic
def create_demo_school(name="Örnek Anadolu Lisesi"):
    school = School.objects.create(name=name, days_per_week=5)

    start = datetime.datetime(2000, 1, 1, 8, 30)
    for i in range(8):
        end = start + datetime.timedelta(minutes=40)
        Period.objects.create(school=school, index=i, name=f"{i + 1}. saat", start_time=start.time(), end_time=end.time())
        start = end + datetime.timedelta(minutes=50 if i == 4 else 10)

    subjects = {
        short: Subject.objects.create(school=school, name=full, short=short, color=color)
        for short, (full, color) in SUBJECTS.items()
    }
    teachers = {
        short: Teacher.objects.create(
            school=school, first_name=first, last_name=last, short=short, max_periods_per_day=6
        )
        for first, last, short in TEACHERS
    }

    room = lambda n: Classroom.objects.create(school=school, name=n, short=n)  # noqa: E731
    lab1, lab2 = room("Fen Lab 1"), room("Fen Lab 2")
    gym = room("Spor Salonu")
    lang1, lang2 = room("Dil 1"), room("Dil 2")

    classes = {}
    lang_groups = {}
    for grade in (9, 10):
        for branch in "AB":
            cls_name = f"{grade}-{branch}"
            cls = SchoolClass.objects.create(
                school=school, name=cls_name, grade=grade, home_classroom=room(f"Derslik {cls_name}")
            )
            division = Division.objects.create(school_class=cls, name="Yabancı dil 2")
            lang_groups[cls_name] = {
                "ALM": Group.objects.create(division=division, name="Almanca"),
                "FRA": Group.objects.create(division=division, name="Fransızca"),
            }
            classes[cls_name] = cls

    def lesson(subject, class_names, teacher_shorts, hours, length=1, rooms=(), groups=()):
        obj = Lesson.objects.create(
            school=school, subject=subjects[subject], periods_per_week=hours, card_length=length
        )
        obj.classes.set([classes[c] for c in class_names])
        obj.teachers.set([teachers[t] for t in teacher_shorts])
        obj.classrooms.set(rooms)
        obj.groups.set(groups)
        return obj

    plan = {
        "9-A": {"TDE": "AYI", "MAT": "ZKA", "İNG": "SAR", "REH": "CAY"},
        "9-B": {"TDE": "AYI", "MAT": "ZKA", "İNG": "SAR", "REH": "DÖZ"},
        "10-A": {"TDE": "MDE", "MAT": "ACE", "İNG": "BDO", "REH": "EŞA"},
        "10-B": {"TDE": "MDE", "MAT": "ACE", "İNG": "BDO", "REH": "MKI"},
    }
    for cls_name, owners in plan.items():
        lesson("TDE", [cls_name], [owners["TDE"]], 5)
        lesson("MAT", [cls_name], [owners["MAT"]], 6, length=2)
        lesson("İNG", [cls_name], [owners["İNG"]], 4)
        lesson("REH", [cls_name], [owners["REH"]], 1)
        lesson("FİZ", [cls_name], ["EŞA"], 2, rooms=[lab1])
        lesson("KİM", [cls_name], ["CAY"], 2, rooms=[lab1, lab2])
        lesson("BİY", [cls_name], ["DÖZ"], 2, rooms=[lab1, lab2])
        lesson("TAR", [cls_name], ["MKI"], 2)
        lesson("COĞ", [cls_name], ["EKO"], 2)
        lesson("BED", [cls_name], ["EKU"], 2, length=2, rooms=[gym])
        lesson("DİN", [cls_name], ["HÖZ"], 2)
        lesson("MÜZ", [cls_name], ["GAK"], 1)

    # Birleşik seçmeli dersler: aynı seviyedeki iki şubenin Almanca ve Fransızca grupları birlikte.
    for grade in (9, 10):
        pair = [f"{grade}-A", f"{grade}-B"]
        lesson("ALM", pair, ["MPO"], 2, rooms=[lang1, lang2], groups=[lang_groups[c]["ALM"] for c in pair])
        lesson("FRA", pair, ["GAK"], 2, rooms=[lang1, lang2], groups=[lang_groups[c]["FRA"] for c in pair])

    # Müsaitlikler: Fizik öğretmeni Cuma gelmiyor; Din öğretmeni için son saat koşullu.
    for p in range(8):
        Availability.objects.create(school=school, teacher=teachers["EŞA"], day=4, period=p, state=Availability.NO)
    for d in range(5):
        Availability.objects.create(
            school=school, teacher=teachers["HÖZ"], day=d, period=7, state=Availability.MAYBE
        )
    return school
