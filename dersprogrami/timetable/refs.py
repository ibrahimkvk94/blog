"""ÜYBS referansları: her kısımda her dersin her haftalık saati için bir kimlik.

Referans "saat sırasına" bağlıdır. Bir dersin bir programdaki saatleri (gün, saat) sırasına
dizilir; 1. saat birinci referansı, 2. saat ikincisini alır. Ders başka saate taşınınca referans
yeni yerine gider; rapor o haftanın gerçek yerleşimiyle ve referanslarla çıkar.
"""

import datetime
import re
from collections import defaultdict

from django.db import transaction

from .models import LessonRef, Substitution

DAY_SHORT = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def lesson_hours(timetable):
    """Ders → sıralı saat listesi [(gün, saat, kart)], yerleşmeyen saatler sonda (gün=None)."""
    hours = defaultdict(list)
    for card in timetable.cards.all() if timetable else []:
        if card.is_placed:
            for i in range(card.length):
                hours[card.lesson_id].append((card.day, card.period + i, card))
        else:
            for i in range(card.length):
                hours[card.lesson_id].append((None, None, card))
    for items in hours.values():
        items.sort(key=lambda h: (h[0] is None, h[0] or 0, h[1] or 0))
    return hours


def ref_index(school):
    """(ders, sınıf ya da None, sıra) → ref."""
    return {
        (r.lesson_id, r.school_class_id, r.ordinal): r.ref
        for r in LessonRef.objects.filter(lesson__school=school)
    }


def class_lessons(school, school_class=None):
    """[(sınıf ya da None, ders)] — ders tablosu satırları (sınıfsız dersler sınıf=None)."""
    rows = []
    lessons = school.lessons.select_related("subject").prefetch_related("classes", "teachers", "groups").order_by("subject__short", "subject__name")
    classes = list(school.classes.all()) if school_class is None else [school_class]
    for cls in classes:
        for lesson in lessons:
            if cls in lesson.classes.all():
                rows.append((cls, lesson))
    if school_class is None:
        rows += [(None, lesson) for lesson in lessons if not lesson.classes.all()]
    return rows


def table(school, timetable, school_class=None):
    """Referans ekranı için satırlar: her ders için saat sırası, o anki yeri ve referansı."""
    hours = lesson_hours(timetable)
    refs = ref_index(school)
    result = []
    for cls, lesson in class_lessons(school, school_class):
        placed = hours.get(lesson.id, [])
        slots = []
        for ordinal in range(1, lesson.periods_per_week + 1):
            where = ""
            if ordinal <= len(placed) and placed[ordinal - 1][0] is not None:
                d, p, _ = placed[ordinal - 1]
                where = f"{DAY_SHORT[d]} {p + 1}"
            slots.append({"ordinal": ordinal, "where": where,
                          "ref": refs.get((lesson.id, cls.id if cls else None, ordinal), "")})
        result.append({
            "cls": cls, "lesson": lesson,
            "groups": ", ".join(sorted({g.name for g in lesson.groups.all()})),
            "teachers": ", ".join(t.full_name for t in lesson.teachers.all()),
            "slots": slots,
        })
    return result


def save_cell(lesson, cls, ordinal, value):
    value = (value or "").strip()[:50]
    lookup = {"lesson": lesson, "school_class": cls, "ordinal": ordinal}
    if value:
        LessonRef.objects.update_or_create(defaults={"ref": value}, **lookup)
    else:
        LessonRef.objects.filter(**lookup).delete()


def save_form(school, data):
    """Formdaki "ref-<ders>-<sınıf|0>-<sıra>" alanlarını kaydeder. Dönüş: değişen hücre sayısı."""
    lessons = {lesson.id: lesson for lesson in school.lessons.all()}
    classes = {c.id: c for c in school.classes.all()}
    current = ref_index(school)
    changed = 0
    with transaction.atomic():
        for key, value in data.items():
            m = re.fullmatch(r"ref-(\d+)-(\d+)-(\d+)", key)
            if not m:
                continue
            lesson = lessons.get(int(m[1]))
            cls = classes.get(int(m[2])) if m[2] != "0" else None
            ordinal = int(m[3])
            if lesson is None or (m[2] != "0" and cls is None) or not 1 <= ordinal <= lesson.periods_per_week:
                continue
            value = value.strip()[:50]
            if current.get((lesson.id, cls.id if cls else None, ordinal), "") != value:
                save_cell(lesson, cls, ordinal, value)
                changed += 1
    return changed


def auto_number(school, timetable, start, step=1, overwrite=False, school_class=None, order="program"):
    """Referansları sırayla numaralar. order="program": kısım → gün → saat (programdaki sıra);
    order="ders": kısım → ders kodu → saat sırası. Rakam dışı ön ek korunur (ör. "A1001")."""
    m = re.fullmatch(r"(\D*)(\d+)", str(start).strip())
    if not m:
        raise ValueError("Başlangıç değeri sayıyla bitmeli (ör. 1001 ya da A1001).")
    prefix, number, width = m[1], int(m[2]), len(m[2])
    hours = lesson_hours(timetable)
    refs = ref_index(school)
    cells = []
    for cls, lesson in class_lessons(school, school_class):
        placed = hours.get(lesson.id, [])
        for ordinal in range(1, lesson.periods_per_week + 1):
            pos = placed[ordinal - 1] if ordinal <= len(placed) else (None, None, None)
            day_key = (pos[0] is None, pos[0] or 0, pos[1] or 0)
            sort = (day_key, lesson.subject.short or lesson.subject.name, ordinal) if order == "program" else (
                lesson.subject.short or lesson.subject.name, lesson.id, ordinal)
            cells.append((cls.sort_key if cls else "~", sort, cls, lesson, ordinal))
    cells.sort(key=lambda c: (c[0], c[1]))
    written = 0
    with transaction.atomic():
        for _, _, cls, lesson, ordinal in cells:
            key = (lesson.id, cls.id if cls else None, ordinal)
            if refs.get(key) and not overwrite:
                continue
            save_cell(lesson, cls, ordinal, f"{prefix}{str(number).zfill(width)}")
            number += step
            written += 1
    return written


def import_text(school, text):
    """Yapıştırılan satırlar: "kısım; ders kodu; saat sırası; ref" ya da "kısım; ders kodu; ref1, ref2, ...".
    Ayraç sekme, noktalı virgül ya da virgül olabilir (Excel'den kopyalama sekme verir).
    Dönüş: (yazılan, hatalar)."""
    classes = {}
    for c in school.classes.all():
        classes[c.name.casefold()] = c
        if c.short:
            classes[c.short.casefold()] = c
    rows = class_lessons(school)
    by_key = defaultdict(list)
    for cls, lesson in rows:
        for code in {lesson.subject.short, lesson.subject.name}:
            if code:
                by_key[((cls.id if cls else None), code.casefold())].append(lesson)
    written, errors = 0, []
    with transaction.atomic():
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            parts = [p.strip() for p in re.split(r"\t|;", line)]
            if len(parts) < 3:
                parts = [p.strip() for p in line.split(",")]
                parts = parts[:2] + [",".join(parts[2:])] if len(parts) >= 3 else parts
            if len(parts) < 3:
                errors.append(f"{n}. satır: en az üç sütun gerekli")
                continue
            cls = classes.get(parts[0].casefold())
            if cls is None:
                errors.append(f"{n}. satır: “{parts[0]}” kısmı bulunamadı")
                continue
            lessons = by_key.get((cls.id, parts[1].casefold()), [])
            if len(lessons) != 1:
                errors.append(f"{n}. satır: {cls.short or cls.name} kısmında “{parts[1]}” dersi " + ("bulunamadı" if not lessons else "birden çok"))
                continue
            lesson = lessons[0]
            if len(parts) >= 4 and parts[2].isdigit():
                pairs = [(int(parts[2]), parts[3])]
            else:
                pairs = list(enumerate([r for r in re.split(r"[,\s]+", parts[2]) if r], start=1))
            for ordinal, ref in pairs:
                if not 1 <= ordinal <= lesson.periods_per_week:
                    errors.append(f"{n}. satır: {ordinal}. saat yok (dersin {lesson.periods_per_week} saati var)")
                    continue
                save_cell(lesson, cls, ordinal, ref)
                written += 1
    return written, errors


def report_rows(timetable, week_start=None, school_class_ids=None, substitutions=True):
    """ÜYBS aktarım listesi: her kısım × ders saati için gün, tarih, saat ve referans.

    Hafta verilip substitutions açıksa o haftanın vekâletleri işlenir: gelmeyen öğretmenin yerine
    vekili yazılır (vekil atanmamışsa öğretmen satırda kalır, "sub" alanında not düşülür)."""
    school = timetable.school
    days = school.day_names
    periods = {p.index: p for p in school.periods.all()}
    hours = lesson_hours(timetable)
    refs = ref_index(school)
    room_names = {r.id: str(r) for r in school.classrooms.all()}
    teachers_by_id = {t.id: t for t in school.teachers.all()}
    subs = {}
    if week_start and substitutions:
        for s in Substitution.objects.filter(
            card__timetable=timetable, absence__date__range=(week_start, week_start + datetime.timedelta(days=6))
        ).select_related("absence"):
            subs[(s.card_id, s.period)] = (s.absence.teacher_id, s.substitute_id)
    rows = []
    for cls, lesson in class_lessons(school, None):
        if school_class_ids and (cls is None or cls.id not in school_class_ids):
            continue
        lesson_teachers = [t.id for t in lesson.teachers.all()]
        for ordinal, (day, period, card) in enumerate(hours.get(lesson.id, []), start=1):
            p = periods.get(period) if period is not None else None
            rooms = ", ".join(room_names.get(r, "") for r in card.room_ids) if card is not None and card.is_placed else ""
            teacher_ids, note = list(lesson_teachers), ""
            sub = subs.get((card.id, period)) if card is not None else None
            if sub and sub[0] in teacher_ids:
                absent, substitute = sub
                if substitute:
                    teacher_ids[teacher_ids.index(absent)] = substitute
                    note = f"{teachers_by_id[absent].full_name} yerine vekil"
                else:
                    note = f"{teachers_by_id[absent].full_name} gelmedi (vekil yok)"
            date = (week_start + datetime.timedelta(days=day)) if (week_start and day is not None) else None
            rows.append({
                "class": (cls.short or cls.name) if cls else "–",
                "class_name": cls.name if cls else "",
                "class_id": cls.id if cls else None,
                "kisim_no": uybs_class_no(cls) if cls else "",
                "code": lesson.subject.short or "",
                "subject": lesson.subject.name,
                "groups": ", ".join(sorted({g.name for g in lesson.groups.all()})),
                "teachers": ", ".join(teachers_by_id[t].full_name for t in teacher_ids),
                "tcs": [teachers_by_id[t].tc_no for t in teacher_ids],
                "teacher_ids": teacher_ids,
                "sub": note,
                "ordinal": ordinal,
                "day_index": day,
                "day": days[day] if day is not None else "yerleşmedi",
                "date": date,
                "period": period + 1 if period is not None else None,
                "start": f"{p.times(day)[0]:%H:%M}" if p and p.times(day)[0] else "",  # o güne özel saat varsa o
                "end": f"{p.times(day)[1]:%H:%M}" if p and p.times(day)[1] else "",
                "time": p.span(day) if p else "",
                "ref": refs.get((lesson.id, cls.id if cls else None, ordinal), ""),
                "room": rooms,
                "sort": ((cls.sort_key if cls else "~"), day if day is not None else 99, period or 0),
            })
    rows.sort(key=lambda r: r["sort"])
    return rows


def uybs_class_no(cls):
    """Kısım no: elle girilmişse o, yoksa adın (ya da kısa adın) başındaki sayı."""
    if cls.uybs_no:
        return cls.uybs_no
    for text in (cls.name, cls.short):
        m = re.match(r"\s*(\d+)", text or "")
        if m:
            return m[1]
    return cls.short or cls.name
