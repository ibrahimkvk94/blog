"""Derslik atama sihirbazı: dersliği belirlenemeyen dersleri iki toplu yolla dersliğe bağlar.

- Sınıflara derslik (sınıf dersliği): tek sınıflı dersler o sınıfın dersliğinde yapılır. Öneri: mevcut
  programlarda o sınıfın derslerinin en çok yapıldığı derslik.
- Ders kodu önekine göre (ders adının varsayılan derslikleri): ör. BİL ile başlayan ders adlarına adı
  "BİL" ile başlayan derslikler önerilir; çözücü o saatte boş olanı seçer.
Bir dersin kendi dersliği seçilmişse ona dokunulmaz (çözücü önce onu kullanır).
"""

import re
from collections import Counter, defaultdict

from .models import Card, Lesson, SchoolClass
from .solver.builder import lesson_rooms
from .textsort import natural_key, tr_lower

PREFIX = re.compile(r"[^\W\d_]+", re.UNICODE)
# Uygulama dersi: adında "(U)" ya da "(Uyg.)" eki olan ("Uygulamaları" gibi ad içi sözcükler sayılmaz)
PRACTICAL = re.compile(r"\(\s*u(yg\.?)?\s*\)", re.IGNORECASE)


def prefix_of(subject):
    m = PREFIX.match(subject.short or subject.name or "")
    return m.group(0).upper() if m else ""


def roomless(school):
    """Sınıfı olan ama hiçbir yoldan dersliği belirlenemeyen dersler."""
    subject_rooms = defaultdict(tuple)
    for subject in school.subjects.prefetch_related("classrooms"):
        subject_rooms[subject.id] = tuple(r.id for r in subject.classrooms.all())
    teacher_home = {t.id: t.home_classroom_id for t in school.teachers.all() if t.home_classroom_id}
    class_home = {c.id: c.home_classroom_id for c in school.classes.all()}
    lessons = Lesson.objects.filter(school=school).select_related("subject").prefetch_related("classrooms", "teachers", "classes")
    return [x for x in lessons if x.classes.all() and not lesson_rooms(x, subject_rooms, teacher_home, class_home)]


def analyze(school):
    lessons = roomless(school)
    rooms = sorted(school.classrooms.all(), key=lambda r: natural_key(r.name))
    # Sınıflar: tek sınıflı dersliksiz dersleri olanlar
    by_class = defaultdict(list)
    for lesson in lessons:
        classes = list(lesson.classes.all())
        if len(classes) == 1:
            by_class[classes[0].id].append(lesson)
    used = defaultdict(Counter)  # sınıf → programlarda kullanılan derslikler
    for class_id, room_id in (Card.objects.filter(timetable__school=school, classroom__isnull=False,
                                                  lesson__classes__isnull=False)
                              .values_list("lesson__classes", "classroom")):
        used[class_id][room_id] += 1
    class_rows = []
    for cls in sorted(SchoolClass.objects.filter(pk__in=by_class), key=lambda c: natural_key(c.name)):
        # Yalnızca ipucu (seçili gelmez): en çok kullanılan derslik çoğu zaman spor salonu/laboratuvar olabilir
        top = used[cls.id].most_common(3)
        names = {r.id: r.name for r in rooms}
        hint = ", ".join(f"{names.get(r, '?')} ({n})" for r, n in top)
        class_rows.append({"cls": cls, "count": len(by_class[cls.id]), "hint": hint})
    # Ders kodu önekleri
    by_prefix = defaultdict(lambda: defaultdict(int))
    for lesson in lessons:
        by_prefix[prefix_of(lesson.subject)][lesson.subject] += 1
    prefix_rows = []
    for prefix, subjects in sorted(by_prefix.items(), key=lambda kv: (-sum(kv[1].values()), kv[0])):
        if not prefix:
            continue
        key = tr_lower(prefix)
        matching = [r.id for r in rooms if tr_lower(r.short or r.name).startswith(key) or tr_lower(r.name).startswith(key)]
        prefix_rows.append({
            "prefix": prefix, "lessons": sum(subjects.values()), "rooms": matching,
            "room_order": [r for r in rooms if r.id in matching] + [r for r in rooms if r.id not in matching],
            "subjects": [{"s": s, "count": n, "practical": bool(PRACTICAL.search(s.name))}
                         for s, n in sorted(subjects.items(), key=lambda kv: natural_key(kv[0].name))],
        })
    multi = sum(1 for lesson in lessons if len(lesson.classes.all()) > 1)
    return {"lessons": len(lessons), "class_rows": class_rows, "prefix_rows": prefix_rows, "rooms": rooms, "multi": multi}


def apply(school, post):
    """Formdaki seçimleri uygular. Dönüş: (atanan sınıf sayısı, derslik eklenen ders adı sayısı)."""
    rooms = {r.id: r for r in school.classrooms.all()}
    classes = {c.id: c for c in school.classes.all()}
    n_classes = 0
    for key, value in post.items():
        if key.startswith("sinif-") and value.isdigit() and int(value) in rooms:
            cls = classes.get(int(key[6:])) if key[6:].isdigit() else None
            if cls is not None and cls.home_classroom_id != int(value):
                cls.home_classroom_id = int(value)
                cls.save(update_fields=["home_classroom"])
                n_classes += 1
    n_subjects = 0
    subjects = {s.id: s for s in school.subjects.all()}
    for key in post:
        if not key.startswith("onek-") or not key.endswith("-derslik"):
            continue
        prefix = key[5:-8]
        chosen = [rooms[int(x)] for x in post.getlist(key) if x.isdigit() and int(x) in rooms]
        if not chosen:
            continue
        for sid in post.getlist(f"onek-{prefix}-ders"):
            subject = subjects.get(int(sid)) if sid.isdigit() else None
            if subject is not None:
                subject.classrooms.add(*chosen)
                n_subjects += 1
    return n_classes, n_subjects
