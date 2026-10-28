"""Program kopyalama: bir programın seçilen verisini aynı kurumda yeni bir programa kopyalar
(ör. 1.YY'den 2.YY). Kimlikler yeniden eşlenir; kopyalar kaynakla hiçbir kayıt paylaşmaz."""

from django.db import transaction

from .models import (
    Availability,
    Building,
    Card,
    CardRelationship,
    Classroom,
    Division,
    DutyPlace,
    Group,
    Lesson,
    LessonRef,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
    TeacherQuota,
    Timetable,
)

PARTS = {
    "ogretmenler": "Öğretmenler (sınırlar, branşlar)",
    "derslikler": "Derslikler ve binalar",
    "siniflar": "Sınıflar, bölünmeler ve gruplar",
    "dersler": "Dersler (öğretmen ve derslik atamalarıyla)",
    "musaitlik": "Müsaitlikler (kapalı / koşullu saatler)",
    "iliskiler": "Kart ilişkileri",
    "nobet": "Nöbet yerleri",
    "refler": "ÜYBS referansları",
    "ogrenciler": "Öğrenciler, seçimleri ve seçmeli kayıtları",
    "yerlesim": "Yayındaki programın yerleşimi (başlangıç sürümü olarak)",
}
# Bir parça başka parçalara dayanır: dersler sınıf/öğretmen/derslik olmadan kopyalanamaz.
REQUIRES = {
    "dersler": {"ogretmenler", "derslikler", "siniflar"},
    "iliskiler": {"dersler"},
    "refler": {"dersler"},
    "ogrenciler": {"dersler"},
    "yerlesim": {"dersler"},
}


def resolve(parts):
    parts = set(parts) & set(PARTS)
    changed = True
    while changed:
        changed = False
        for part in list(parts):
            missing = REQUIRES.get(part, set()) - parts
            if missing:
                parts |= missing
                changed = True
    return parts


def _clone(obj, **overrides):
    data = {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields if not f.primary_key}
    data.update(overrides)
    return type(obj).objects.create(**data)


@transaction.atomic
def copy_program(source, name, parts):
    """Dönüş: (yeni program, kopyalanan parçalar)."""
    parts = resolve(parts)
    target = School.objects.create(
        institution=source.institution, name=name[:200], days_per_week=source.days_per_week,
        weeks_count=source.weeks_count, terms_count=source.terms_count, duties_per_teacher=source.duties_per_teacher,
        uybs_settings=source.uybs_settings,
    )
    for p in source.periods.all():
        _clone(p, school_id=target.id)

    buildings, rooms, subjects, teachers, classes, groups, lessons = {}, {}, {}, {}, {}, {}, {}
    for s in source.subjects.all():
        subjects[s.id] = _clone(s, school_id=target.id)
    if "derslikler" in parts:
        for b in source.buildings.all():
            buildings[b.id] = _clone(b, school_id=target.id)
        for r in source.classrooms.all():
            rooms[r.id] = _clone(r, school_id=target.id, building_id=buildings[r.building_id].id if r.building_id else None)
        for s in source.subjects.prefetch_related("classrooms"):
            subjects[s.id].classrooms.set([rooms[r.id] for r in s.classrooms.all()])
    if "ogretmenler" in parts:
        for t in source.teachers.prefetch_related("subjects"):
            teachers[t.id] = _clone(t, school_id=target.id,
                                    home_classroom_id=rooms[t.home_classroom_id].id if t.home_classroom_id in rooms else None)
            teachers[t.id].subjects.set([subjects[s.id] for s in t.subjects.all()])
    if "siniflar" in parts:
        for c in source.classes.prefetch_related("divisions__groups"):
            classes[c.id] = _clone(
                c, school_id=target.id,
                home_classroom_id=rooms[c.home_classroom_id].id if c.home_classroom_id in rooms else None,
                class_teacher_id=teachers[c.class_teacher_id].id if c.class_teacher_id in teachers else None,
            )
            for d in c.divisions.all():
                new_division = _clone(d, school_class_id=classes[c.id].id)
                for g in d.groups.all():
                    groups[g.id] = _clone(g, division_id=new_division.id)
    if "dersler" in parts:
        for lesson in source.lessons.prefetch_related("classes", "groups", "teachers", "classrooms"):
            new = _clone(lesson, school_id=target.id, subject_id=subjects[lesson.subject_id].id)
            new.classes.set([classes[c.id] for c in lesson.classes.all()])
            new.groups.set([groups[g.id] for g in lesson.groups.all()])
            new.teachers.set([teachers[t.id] for t in lesson.teachers.all()])
            new.classrooms.set([rooms[r.id] for r in lesson.classrooms.all()])
            lessons[lesson.id] = new
        TeacherQuota.objects.bulk_create(  # öğretmen havuzu kotaları
            TeacherQuota(school=target, subject=subjects[q.subject_id], teacher=teachers[q.teacher_id], count=q.count)
            for q in source.teacher_quotas.all() if q.subject_id in subjects and q.teacher_id in teachers
        )
    if "musaitlik" in parts:
        maps = {"teacher": teachers, "school_class": classes, "classroom": rooms, "subject": subjects, "lesson": lessons}
        rows = []
        for a in source.availabilities.all():
            target_field = next((f for f in Availability.TARGET_FIELDS if getattr(a, f + "_id")), None)
            if target_field is None:
                rows.append(Availability(school=target, day=a.day, period=a.period, state=a.state))
            elif getattr(a, target_field + "_id") in maps[target_field]:
                rows.append(Availability(school=target, day=a.day, period=a.period, state=a.state,
                                         **{target_field: maps[target_field][getattr(a, target_field + "_id")]}))
        Availability.objects.bulk_create(rows)
    if "iliskiler" in parts:
        for rel in source.relationships.prefetch_related("lessons", "subjects", "lessons_b", "subjects_b", "classes", "teachers", "classrooms"):
            new = _clone(rel, school_id=target.id)
            new.lessons.set([lessons[x.id] for x in rel.lessons.all()])
            new.lessons_b.set([lessons[x.id] for x in rel.lessons_b.all()])
            new.subjects.set([subjects[x.id] for x in rel.subjects.all()])
            new.subjects_b.set([subjects[x.id] for x in rel.subjects_b.all()])
            new.classes.set([classes[x.id] for x in rel.classes.all()])
            new.teachers.set([teachers[x.id] for x in rel.teachers.all()])
            new.classrooms.set([rooms[x.id] for x in rel.classrooms.all()])
    if "nobet" in parts:
        for place in source.duty_places.all():
            _clone(place, school_id=target.id)
    if "refler" in parts:
        LessonRef.objects.bulk_create(
            LessonRef(lesson=lessons[r.lesson_id], school_class=classes.get(r.school_class_id), ordinal=r.ordinal, ref=r.ref)
            for r in LessonRef.objects.filter(lesson__school=source)
        )
    if "ogrenciler" in parts:
        for st in source.students.prefetch_related("groups", "choices", "lessons"):
            new = _clone(st, school_id=target.id, school_class_id=classes[st.school_class_id].id if st.school_class_id in classes else None)
            new.groups.set([groups[g.id] for g in st.groups.all() if g.id in groups])
            new.choices.set([subjects[c.id] for c in st.choices.all()])
            for lesson in st.lessons.all():
                lessons[lesson.id].students.add(new)
    if "yerlesim" in parts:
        timetable = source.active_timetable or source.timetables.filter(status__in=[Timetable.OK, Timetable.PARTIAL]).first()
        if timetable is not None:
            copy = Timetable.objects.create(school=target, name=f"{timetable.name} (kopya)", status=timetable.status, mode=timetable.mode)
            Card.objects.bulk_create(
                Card(timetable=copy, lesson=lessons[c.lesson_id], length=c.length, day=c.day, period=c.period,
                     classroom_id=rooms[c.classroom_id].id if c.classroom_id in rooms else None,
                     extra_rooms=[rooms[r].id for r in c.extra_rooms or [] if r in rooms], locked=c.locked)
                for c in timetable.cards.all()
            )
            from .versions import save_version

            save_version(copy, note=f"{source.name} programından kopyalandı", auto=True)
    return target, parts
