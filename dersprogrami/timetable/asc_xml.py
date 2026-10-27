"""aSc TimeTables XML biçimiyle içe ve dışa aktarma.

aSc'nin "aSc TimeTables XML" dışa aktarımı tablo başına bir öğe ve satır başına bir alt öğe içerir
(periods/period, subjects/subject, lessons/lesson, cards/card …). Bağlantılar kimlik listeleriyle
kurulur (ör. lesson@classids="C1,C2"). Günler, haftalar ve dönemler bit dizgileridir
(card@days="01000" = Salı).

Notlar:
- aSc her sınıf için "Tüm sınıf" grubu tanımlar (entireclass="1"); bu grup bizde "grup seçilmemiş"
  anlamına gelir. Diğer gruplar divisiontag değerine göre bölünmelere ayrılır.
- aSc kart satırları ders saati başınadır; içe aktarırken aynı dersin aynı gündeki ardışık saatleri
  periodspercard uzunluğuna kadar tek blok kartta birleştirilir.
"""

import datetime
import xml.etree.ElementTree as ET
from collections import defaultdict

from django.db import transaction

from .models import (
    Availability,
    Building,
    Card,
    Classroom,
    Division,
    Group,
    Lesson,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
    Timetable,
)

PALETTE = ["#dfe7fd", "#fde2e4", "#e2ece9", "#fff1e6", "#e9f5db", "#f0efeb", "#cddafd", "#fad2e1", "#bee1e6", "#eae4e9"]


class AscImportError(Exception):
    pass


# --- dışa aktarma ----------------------------------------------------------------------------


def _bits(indices, count):
    return "".join("1" if i in indices else "0" for i in range(count))


def _mask_string(mask, count):
    return _bits({i for i in range(count) if mask is None or mask >> i & 1}, count)


def _table(root, tag, columns):
    return ET.SubElement(root, tag, options="canadd,export:silent", columns=",".join(columns))


def export_school(school, timetable=None):
    root = ET.Element("timetable", ascttversion="2026", importtype="database", options="idprefix:DP,daynumbering1")
    days, weeks, terms = school.days_per_week, school.weeks_count, school.terms_count

    periods = _table(root, "periods", ["period", "name", "short", "starttime", "endtime"])
    for p in school.periods.all():
        ET.SubElement(
            periods,
            "period",
            period=str(p.index + 1),
            name=p.name,
            short=str(p.index + 1),
            starttime=f"{p.start_time:%H:%M}" if p.start_time else "",
            endtime=f"{p.end_time:%H:%M}" if p.end_time else "",
        )

    daysdefs = _table(root, "daysdefs", ["id", "days", "name", "short"])
    ET.SubElement(daysdefs, "daysdef", id="DALL", days=",".join(_bits({d}, days) for d in range(days)), name="Herhangi bir gün", short="X")
    for d, name in enumerate(school.day_names):
        ET.SubElement(daysdefs, "daysdef", id=f"D{d}", days=_bits({d}, days), name=name, short=name[:3])

    lessons = list(school.lessons.select_related("subject").prefetch_related("classes", "groups__division", "teachers", "classrooms"))
    week_masks = {lesson.weeks_mask for lesson in lessons} | {None}
    term_masks = {lesson.terms_mask for lesson in lessons} | {None}
    weeksdefs = _table(root, "weeksdefs", ["id", "weeks", "name", "short"])
    for mask in week_masks:
        ET.SubElement(weeksdefs, "weeksdef", id=f"W{mask or 'ALL'}", weeks=_mask_string(mask, weeks), name="Her hafta" if mask is None else f"Hafta {mask}", short="H")
    termsdefs = _table(root, "termsdefs", ["id", "terms", "name", "short"])
    for mask in term_masks:
        ET.SubElement(termsdefs, "termsdef", id=f"P{mask or 'ALL'}", terms=_mask_string(mask, terms), name="Tüm yıl" if mask is None else f"Dönem {mask}", short="Y")

    subjects = _table(root, "subjects", ["id", "name", "short", "color"])
    for s in school.subjects.all():
        ET.SubElement(subjects, "subject", id=f"S{s.pk}", name=s.name, short=s.short or s.name[:4], color=s.color)

    teachers = _table(root, "teachers", ["id", "firstname", "lastname", "name", "short"])
    for t in school.teachers.all():
        ET.SubElement(teachers, "teacher", id=f"T{t.pk}", firstname=t.first_name, lastname=t.last_name, name=f"{t.first_name} {t.last_name}", short=t.short or "")

    buildings = _table(root, "buildings", ["id", "name"])
    for b in school.buildings.all():
        ET.SubElement(buildings, "building", id=f"B{b.pk}", name=b.name)

    classrooms = _table(root, "classrooms", ["id", "name", "short", "capacity", "buildingid"])
    for r in school.classrooms.all():
        ET.SubElement(
            classrooms, "classroom", id=f"R{r.pk}", name=r.name, short=r.short or r.name,
            capacity=str(r.capacity or "*"), buildingid=f"B{r.building_id}" if r.building_id else "",
        )

    classes = list(school.classes.prefetch_related("divisions__groups"))
    grades = _table(root, "grades", ["grade", "name", "short"])
    for grade in sorted({c.grade for c in classes if c.grade is not None}):
        ET.SubElement(grades, "grade", grade=str(grade), name=f"{grade}. sınıf", short=str(grade))
    classes_el = _table(root, "classes", ["id", "name", "short", "classroomids", "teacherid", "grade"])
    groups_el = _table(root, "groups", ["id", "classid", "name", "entireclass", "divisiontag", "studentcount"])
    for c in classes:
        ET.SubElement(
            classes_el, "class", id=f"C{c.pk}", name=c.name, short=c.short or c.name,
            classroomids=f"R{c.home_classroom_id}" if c.home_classroom_id else "", grade=str(c.grade or ""),
            teacherid=f"T{c.class_teacher_id}" if c.class_teacher_id else "",
        )
        ET.SubElement(groups_el, "group", id=f"G{c.pk}_0", classid=f"C{c.pk}", name="Tüm sınıf", entireclass="1", divisiontag="0", studentcount="")
        for tag, division in enumerate(c.divisions.all(), start=1):
            for g in division.groups.all():
                ET.SubElement(
                    groups_el, "group", id=f"G{g.pk}", classid=f"C{c.pk}", name=g.name, entireclass="0",
                    divisiontag=str(tag), studentcount=str(g.student_count or ""),
                )

    lessons_el = _table(
        root,
        "lessons",
        ["id", "classids", "groupids", "subjectid", "periodspercard", "periodsperweek", "teacherids", "classroomids", "weeksdefid", "termsdefid", "daysdefid"],
    )
    for lesson in lessons:
        lesson_classes = list(lesson.classes.all())
        chosen = {g.division.school_class_id: g for g in lesson.groups.all()}
        ET.SubElement(
            lessons_el,
            "lesson",
            id=f"L{lesson.pk}",
            classids=",".join(f"C{c.pk}" for c in lesson_classes),
            groupids=",".join(f"G{chosen[c.pk].pk}" if c.pk in chosen else f"G{c.pk}_0" for c in lesson_classes),
            subjectid=f"S{lesson.subject_id}",
            periodspercard=str(lesson.card_length),
            periodsperweek=f"{lesson.periods_per_week:.1f}",
            teacherids=",".join(f"T{t.pk}" for t in lesson.teachers.all()),
            classroomids=",".join(f"R{r.pk}" for r in lesson.classrooms.all()),
            weeksdefid=f"W{lesson.weeks_mask or 'ALL'}",
            termsdefid=f"P{lesson.terms_mask or 'ALL'}",
            daysdefid="DALL",
        )

    if timetable is not None:
        cards_el = _table(root, "cards", ["lessonid", "period", "days", "weeks", "terms", "classroomids", "locked"])
        lesson_masks = {lesson.pk: (lesson.weeks_mask, lesson.terms_mask) for lesson in lessons}
        for card in timetable.cards.filter(day__isnull=False).order_by("day", "period"):
            weeks_mask, terms_mask = lesson_masks.get(card.lesson_id, (None, None))
            for i in range(card.length):
                ET.SubElement(
                    cards_el,
                    "card",
                    lessonid=f"L{card.lesson_id}",
                    period=str(card.period + i + 1),
                    days=_bits({card.day}, days),
                    weeks=_mask_string(weeks_mask, weeks),
                    terms=_mask_string(terms_mask, terms),
                    classroomids=",".join(f"R{r}" for r in card.room_ids),
                    locked="1" if card.locked else "0",
                )

    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# --- içe aktarma -----------------------------------------------------------------------------


def _ids(value):
    return [v for v in (value or "").split(",") if v]


def _bit_set(value):
    return {i for i, ch in enumerate(value or "") if ch == "1"}


def _union_bits(value):
    result = set()
    for part in _ids(value):
        result |= _bit_set(part)
    return result


def _mask(bits, count):
    bits = {b for b in bits if b < count}
    if not bits or len(bits) == count:
        return None
    return sum(1 << b for b in bits)


def _time(value):
    try:
        hour, minute = (int(x) for x in (value or "").split(":")[:2])
        return datetime.time(hour, minute)
    except (ValueError, TypeError):
        return None


def _int(value, default=0):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def import_school(data, name=None):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise AscImportError(f"XML okunamadı ({exc}).")
    if root.tag != "timetable":
        raise AscImportError("Bu bir aSc TimeTables XML dosyası değil (kök öğe <timetable> olmalı).")

    def rows(table, tag):
        parent = root.find(table)
        return parent.findall(tag) if parent is not None else []

    period_rows = sorted(rows("periods", "period"), key=lambda p: _int(p.get("period")))
    if not period_rows:
        raise AscImportError("Dosyada ders saati (periods) yok.")
    period_index = {p.get("period"): i for i, p in enumerate(period_rows)}

    day_lengths = [len(part) for d in rows("daysdefs", "daysdef") for part in _ids(d.get("days"))]
    day_lengths += [len(c.get("days") or "") for c in rows("cards", "card")]
    days = min(7, max([n for n in day_lengths if n] or [5]))
    weeks = max([len(part) for w in rows("weeksdefs", "weeksdef") for part in _ids(w.get("weeks"))] or [1])
    terms = max([len(part) for t in rows("termsdefs", "termsdef") for part in _ids(t.get("terms"))] or [1])

    with transaction.atomic():
        school = School.objects.create(name=root.get("name") or name or "aSc içe aktarımı", days_per_week=days, weeks_count=weeks, terms_count=terms)
        for i, p in enumerate(period_rows):
            Period.objects.create(school=school, index=i, name=p.get("name") or f"{i + 1}. saat", start_time=_time(p.get("starttime")), end_time=_time(p.get("endtime")))

        subjects = {}
        for i, s in enumerate(rows("subjects", "subject")):
            color = s.get("color") if (s.get("color") or "").startswith("#") and len(s.get("color")) == 7 else PALETTE[i % len(PALETTE)]
            subjects[s.get("id")] = Subject.objects.create(school=school, name=s.get("name") or "?", short=(s.get("short") or "")[:20], color=color)

        teachers = {}
        for t in rows("teachers", "teacher"):
            first, last = t.get("firstname") or "", t.get("lastname") or ""
            if not first and not last:
                first, _, last = (t.get("name") or t.get("short") or "?").partition(" ")
            teachers[t.get("id")] = Teacher.objects.create(school=school, first_name=first, last_name=last, short=(t.get("short") or "")[:60])

        buildings = {b.get("id"): Building.objects.create(school=school, name=b.get("name") or "?") for b in rows("buildings", "building")}
        rooms = {}
        for r in rows("classrooms", "classroom"):
            rooms[r.get("id")] = Classroom.objects.create(
                school=school, name=r.get("name") or "?", short=(r.get("short") or "")[:60],
                capacity=_int(r.get("capacity"), None) if (r.get("capacity") or "").strip("*") else None,
                building=buildings.get(r.get("buildingid")),
            )

        classes = {}
        for c in rows("classes", "class"):
            home = next((rooms[r] for r in _ids(c.get("classroomids")) if r in rooms), None)
            short = (c.get("short") or "").strip()
            classes[c.get("id")] = SchoolClass.objects.create(
                school=school, name=c.get("name") or short or "?", short=short[:30] if short != c.get("name") else "",
                grade=_int(c.get("grade"), None), home_classroom=home,
                class_teacher=teachers.get(c.get("teacherid")),
            )

        groups = {}  # aSc grup kimliği -> Group (tüm sınıf grupları için None)
        divisions = {}
        for g in rows("groups", "group"):
            cls = classes.get(g.get("classid"))
            if cls is None:
                continue
            if g.get("entireclass") == "1":
                groups[g.get("id")] = None
                continue
            tag = g.get("divisiontag") or "0"
            if (cls.pk, tag) not in divisions:
                divisions[(cls.pk, tag)] = Division.objects.create(school_class=cls, name=f"Bölünme {tag}")
            groups[g.get("id")] = Group.objects.create(
                division=divisions[(cls.pk, tag)], name=g.get("name") or "?", student_count=_int(g.get("studentcount"), None) or None
            )

        # aSc bölünmeleri yalnızca numara taşır; adı grup adlarından oluşturulur (ör. "Grup 1 / Grup 2").
        for division in divisions.values():
            names = list(division.groups.values_list("name", flat=True))
            if names:
                division.name = " / ".join(names)[:50]
                division.save(update_fields=["name"])

        days_defs = {d.get("id"): _union_bits(d.get("days")) for d in rows("daysdefs", "daysdef")}
        weeks_defs = {w.get("id"): _union_bits(w.get("weeks")) for w in rows("weeksdefs", "weeksdef")}
        terms_defs = {t.get("id"): _union_bits(t.get("terms")) for t in rows("termsdefs", "termsdef")}

        lessons = {}
        for item in rows("lessons", "lesson"):
            lesson_classes = [classes[c] for c in _ids(item.get("classids")) if c in classes]
            subject = subjects.get(item.get("subjectid"))
            if not lesson_classes or subject is None:
                continue
            lesson = Lesson.objects.create(
                school=school,
                subject=subject,
                periods_per_week=max(1, _int(item.get("periodsperweek"), 1)),
                card_length=max(1, _int(item.get("periodspercard"), 1)),
                weeks_mask=_mask(weeks_defs.get(item.get("weeksdefid"), set()), weeks),
                terms_mask=_mask(terms_defs.get(item.get("termsdefid"), set()), terms),
            )
            lesson.classes.set(lesson_classes)
            lesson.groups.set([groups[g] for g in _ids(item.get("groupids")) if groups.get(g)])
            lesson.teachers.set([teachers[t] for t in _ids(item.get("teacherids")) if t in teachers])
            lesson.classrooms.set([rooms[r] for r in _ids(item.get("classroomids")) if r in rooms])
            allowed = days_defs.get(item.get("daysdefid"))
            if allowed and len({d for d in allowed if d < days}) < days:
                Availability.objects.bulk_create(
                    Availability(school=school, lesson=lesson, day=d, period=p)
                    for d in range(days)
                    if d not in allowed
                    for p in range(len(period_rows))
                )
            lessons[item.get("id")] = lesson

        _infer_shared_rooms(rows("cards", "card"), lessons, rooms, period_index)
        timetable = _import_cards(school, rows("cards", "card"), lessons, rooms, period_index)
    return school, timetable


def _infer_shared_rooms(card_rows, lessons, rooms, period_index):
    """aSc'de bir derslik aynı anda birden çok dersi alabilir (spor salonu gibi); XML bu ayarı taşımaz.
    Kartlarda aynı anda aynı derslikte görülen en çok ders sayısı dersliğin sınırı olarak alınır."""
    usage = defaultdict(set)
    for row in card_rows:
        lesson = lessons.get(row.get("lessonid"))
        period = period_index.get(row.get("period"))
        if lesson is None or period is None:
            continue
        for day in _bit_set(row.get("days")):
            for room_id in _ids(row.get("classroomids")):
                if room_id in rooms:
                    usage[(room_id, day, period, row.get("weeks"), row.get("terms"))].add(lesson.pk)
    most = defaultdict(int)
    for (room_id, *_rest), lesson_ids in usage.items():
        most[room_id] = max(most[room_id], len(lesson_ids))
    for room_id, count in most.items():
        if count > 1:
            room = rooms[room_id]
            room.max_lessons = count
            room.save(update_fields=["max_lessons"])


def _import_cards(school, card_rows, lessons, rooms, period_index):
    slots = defaultdict(list)  # (ders, gün) -> [(saat, derslik, kilitli)]
    for row in card_rows:
        lesson = lessons.get(row.get("lessonid"))
        period = period_index.get(row.get("period"))
        day_bits = sorted(_bit_set(row.get("days")))
        if lesson is None or period is None or not day_bits:
            continue
        card_rooms = tuple(rooms[r] for r in _ids(row.get("classroomids")) if r in rooms)
        slots[(lesson, day_bits[0])].append((period, card_rooms, row.get("locked") == "1"))
    if not slots:
        return None

    timetable = Timetable.objects.create(school=school, name="aSc'den içe aktarılan", status=Timetable.OK)
    cards = []
    used = defaultdict(int)
    for (lesson, day), items in slots.items():
        items = sorted(set(items), key=lambda x: x[0])
        i = 0
        while i < len(items):
            start, card_rooms, locked = items[i]
            length = 1
            while (
                i + length < len(items)
                and length < lesson.card_length
                and items[i + length][0] == start + length
            ):
                length += 1
            cards.append(
                Card(
                    timetable=timetable, lesson=lesson, length=length, day=day, period=start, locked=locked,
                    classroom=card_rooms[0] if card_rooms else None, extra_rooms=[r.pk for r in card_rooms[1:]],
                )
            )
            used[lesson.pk] += length
            i += length
    for lesson in lessons.values():
        missing = lesson.periods_per_week - used[lesson.pk]
        while missing > 0:
            length = min(lesson.card_length, missing)
            cards.append(Card(timetable=timetable, lesson=lesson, length=length))
            missing -= length
    Card.objects.bulk_create(cards)
    if any(c.day is None for c in cards):
        Timetable.objects.filter(pk=timetable.pk).update(status=Timetable.PARTIAL)
        timetable.refresh_from_db()
    from .versions import save_version

    save_version(timetable, note="aSc'den içe aktarıldı", auto=True)
    return timetable
