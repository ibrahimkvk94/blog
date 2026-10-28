"""Öğrenciler ve seçmeli dersler (aSc'deki seminer/seçmeli mantığı).

- Öğrenci bir sınıftadır, bölünmelerde gruplara girer ve seçtiği dersleri (ders adı) belirtir.
- "Seçmeli" işaretli dersler şube gibidir: aynı ders adının birden çok seçmeli dersi olabilir.
  Dağıtım her öğrenciyi seçtiği ders adının, programına çakışmayan ve kontenjanı dolmamış
  şubesine yerleştirir.
- Öğrencinin girdiği dersler: sınıfının seçmeli olmayan dersleri (grup varsa yalnız kendi grubu)
  ve kayıtlı olduğu seçmeli dersler. Üretimde aynı öğrencinin dersleri çakışmaz.
"""

import re
from collections import Counter, defaultdict

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import Lesson, School, Student, Timetable


# --- öğrencinin dersleri ------------------------------------------------------------------------

def _lesson_index(school):
    lessons = list(school.lessons.prefetch_related("classes", "groups__division", "students"))
    return lessons


def attendance(school, students=None, lessons=None):
    """{öğrenci kimliği: girdiği ders kimlikleri kümesi}."""
    lessons = lessons if lessons is not None else _lesson_index(school)
    students = students if students is not None else list(school.students.prefetch_related("groups"))
    by_class = defaultdict(list)
    for lesson in lessons:
        if lesson.elective:
            continue
        groups_by_class = defaultdict(set)
        for g in lesson.groups.all():
            groups_by_class[g.division.school_class_id].add(g.id)
        for c in lesson.classes.all():
            by_class[c.id].append((lesson.id, groups_by_class.get(c.id)))
    enrolled = defaultdict(set)
    for lesson in lessons:
        if lesson.elective:
            for s in lesson.students.all():
                enrolled[s.id].add(lesson.id)
    result = {}
    for s in students:
        mine = {g.id for g in s.groups.all()}
        attends = {lid for lid, groups in by_class.get(s.school_class_id, []) if not groups or groups & mine}
        result[s.id] = attends | enrolled[s.id]
    return result


def solver_student_keys(school):
    """Çözücü için {ders kimliği: öğrenci anahtarları}. Seçmeli ders içeren aynı ders kümesine sahip
    öğrenciler tek anahtarda birleşir; böylece kısıt sayısı öğrenci sayısıyla büyümez."""
    lessons = _lesson_index(school)
    electives = {lesson.id for lesson in lessons if lesson.elective}
    if not electives:
        return {}
    sets = {frozenset(ls) for ls in attendance(school, lessons=lessons).values() if ls & electives and len(ls) > 1}
    keys = defaultdict(list)
    for n, lesson_set in enumerate(sorted(sets, key=sorted)):
        for lesson_id in lesson_set:
            keys[lesson_id].append(f"s{n}")
    return {k: tuple(v) for k, v in keys.items()}


def _placed_cells(timetable):
    """{ders kimliği: [(gün, saat), ...]} yerleşmiş kartlardan."""
    cells = defaultdict(list)
    if timetable is None:
        return cells
    for card in timetable.cards.filter(day__isnull=False):
        cells[card.lesson_id] += [(card.day, card.period + i) for i in range(card.length)]
    return cells


def clashes(school, timetable):
    """Aynı saatte iki dersi olan öğrenciler: [(öğrenci, [(gün, saat, [ders, ...])])]."""
    if timetable is None:
        return []
    cells = _placed_cells(timetable)
    lessons = {lesson.id: lesson for lesson in school.lessons.select_related("subject")}
    students = list(school.students.prefetch_related("groups").select_related("school_class"))
    result = []
    for s in students:
        busy = defaultdict(list)
        for lid in attendance(school, [s]).get(s.id, ()):
            for cell in cells.get(lid, ()):
                busy[cell].append(lessons[lid])
        bad = [(d, p, ls) for (d, p), ls in sorted(busy.items()) if len(ls) > 1]
        if bad:
            result.append((s, bad))
    return result


# --- dağıtım ------------------------------------------------------------------------------------

def distribute(school, timetable=None, reset=False):
    """Öğrencileri seçtikleri ders adlarının seçmeli şubelerine dağıtır.

    Her seçim için: zaten kayıtlıysa korunur (reset değilse); yoksa kontenjanı dolmamış şubeler
    arasından öğrencinin programıyla en az çakışan, sonra en az dolu olan seçilir. Az şubesi olan
    seçimler önce dağıtılır. Dönüş: {"assigned": n, "kept": n, "unassigned": [(öğrenci, ders adı, neden)]}."""
    lessons = list(school.lessons.filter(elective=True).select_related("subject").prefetch_related("students"))
    sections = defaultdict(list)
    for lesson in lessons:
        sections[lesson.subject_id].append(lesson)
    cells = _placed_cells(timetable)
    students = list(school.students.prefetch_related("groups", "choices"))
    with transaction.atomic():
        if reset:
            for lesson in lessons:
                lesson.students.clear()
        members = {lesson.id: set() if reset else {s.id for s in lesson.students.all()} for lesson in lessons}
        base = attendance(school, students)  # seçmeliler dahil mevcut durum
        busy = {}
        for s in students:
            own = base[s.id] - ({lesson.id for lesson in lessons} if reset else set())
            busy[s.id] = Counter(cell for lid in own for cell in cells.get(lid, ()))
        todo = [(s, subject) for s in students for subject in s.choices.all()]
        todo.sort(key=lambda item: (len(sections.get(item[1].id, [])), item[0].id))
        assigned = kept = 0
        unassigned = []
        for s, subject in todo:
            options = sections.get(subject.id, [])
            if not options:
                unassigned.append((s, subject, "bu ders adının seçmeli dersi yok"))
                continue
            if any(s.id in members[o.id] for o in options):
                kept += 1
                continue
            free = [o for o in options if o.capacity is None or len(members[o.id]) < o.capacity]
            if not free:
                unassigned.append((s, subject, "tüm şubelerin kontenjanı dolu"))
                continue
            best = min(free, key=lambda o: (
                sum(busy[s.id][c] for c in cells.get(o.id, ())),
                len(members[o.id]) / (o.capacity or 1000),
                o.id,
            ))
            members[best.id].add(s.id)
            busy[s.id].update(cells.get(best.id, ()))
            assigned += 1
        for lesson in lessons:
            lesson.students.set(members[lesson.id])
    return {"assigned": assigned, "kept": kept, "unassigned": unassigned}


# --- içe aktarma ---------------------------------------------------------------------------------

def import_text(school, text):
    """Satır: "numara; ad soyad; sınıf; gruplar; seçtiği dersler" (sekme ya da noktalı virgül).
    Gruplar ve seçimler virgülle ayrılır; seçimler ders kodu (kısa ad) ya da ders adıdır.
    Aynı numaralı öğrenci varsa güncellenir. Dönüş: (eklenen, güncellenen, hatalar)."""
    classes = {}
    for c in school.classes.prefetch_related("divisions__groups"):
        for key in (c.name, c.short):
            if key:
                classes[key.casefold()] = c
    subjects = {}
    for s in school.subjects.all():
        for key in (s.short, s.name):
            if key:
                subjects.setdefault(key.casefold(), s)
    existing = {s.number: s for s in school.students.all() if s.number}
    added = updated = 0
    errors = []
    with transaction.atomic():
        for n, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            parts = [p.strip() for p in re.split(r"\t|;", line)] + ["", "", "", ""]
            number, name, class_name, group_names, choice_names = parts[:5]
            if not name:
                errors.append(f"{n}. satır: ad soyad yok")
                continue
            first, _, last = name.rpartition(" ") if " " in name else (name, "", "")
            cls = classes.get(class_name.casefold()) if class_name else None
            if class_name and cls is None:
                errors.append(f"{n}. satır: “{class_name}” sınıfı bulunamadı")
            student = existing.get(number) if number else None
            if student is None:
                student = Student.objects.create(school=school, number=number[:30], first_name=first[:100], last_name=last[:100], school_class=cls)
                added += 1
                if number:
                    existing[number] = student
            else:
                student.first_name, student.last_name, student.school_class = first[:100], last[:100], cls
                student.save()
                updated += 1
            groups = []
            if cls is not None:
                by_name = {g.name.casefold(): g for d in cls.divisions.all() for g in d.groups.all()}
                for g in filter(None, (x.strip() for x in group_names.split(","))):
                    if g.casefold() in by_name:
                        groups.append(by_name[g.casefold()])
                    else:
                        errors.append(f"{n}. satır: {cls} sınıfında “{g}” grubu yok")
            student.groups.set(groups)
            chosen = []
            for c in filter(None, (x.strip() for x in choice_names.split(","))):
                if c.casefold() in subjects:
                    chosen.append(subjects[c.casefold()])
                else:
                    errors.append(f"{n}. satır: “{c}” dersi bulunamadı")
            student.choices.set(chosen)
    return added, updated, errors


# --- görünümler ---------------------------------------------------------------------------------

def _timetable(school, request):
    pk = request.GET.get("program") or request.POST.get("program")
    if pk and pk.isdigit():
        tt = school.timetables.filter(pk=pk).first()
        if tt is not None:
            return tt
    return school.active_timetable or school.timetables.filter(status__in=[Timetable.OK, Timetable.PARTIAL]).first()


def students_page(request, pk):
    school = get_object_or_404(School, pk=pk)
    timetable = _timetable(school, request)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "import":
            added, updated, errors = import_text(school, request.POST.get("text", ""))
            messages.success(request, f"{added} öğrenci eklendi, {updated} öğrenci güncellendi.")
            for e in errors[:12]:
                messages.warning(request, e)
        elif action == "distribute":
            result = distribute(school, timetable, reset=request.POST.get("reset") == "1")
            messages.success(request, f"{result['assigned']} seçim dağıtıldı, {result['kept']} seçim olduğu gibi kaldı.")
            for s, subject, reason in result["unassigned"][:12]:
                messages.warning(request, f"{s.full_name} – {subject.short or subject.name}: {reason}")
            if len(result["unassigned"]) > 12:
                messages.warning(request, f"… ve {len(result['unassigned']) - 12} seçim daha dağıtılamadı.")
        elif action == "delete":
            ids = [int(x) for x in request.POST.getlist("sec") if x.isdigit()]
            n, _ = school.students.filter(pk__in=ids).delete() if ids else (0, None)
            messages.info(request, f"{n} kayıt silindi.")
        elif action == "delete_all" and request.POST.get("confirm") == "SİL":
            school.students.all().delete()
            messages.info(request, "Tüm öğrenciler silindi.")
        query = f"?program={timetable.pk}" if timetable else ""
        return redirect(reverse("timetable:students", args=[school.pk]) + query)

    class_id = request.GET.get("sinif")
    qs = school.students.select_related("school_class").prefetch_related("groups", "choices", "lessons__subject")
    if class_id and class_id.isdigit():
        qs = qs.filter(school_class_id=class_id)
    students = list(qs)
    electives = list(
        school.lessons.filter(elective=True).select_related("subject").prefetch_related("teachers", "students", "classes")
    )
    demand = Counter(subject_id for s in school.students.prefetch_related("choices") for subject_id in (c.id for c in s.choices.all()))
    clash_list = clashes(school, timetable)
    clash_ids = {s.id for s, _ in clash_list}
    from .views import _nav

    return render(request, "timetable/students.html", _nav(
        school, "students", students=students, classes=list(school.classes.all()), class_id=int(class_id) if class_id and class_id.isdigit() else None,
        electives=[{"lesson": e, "count": e.students.count(), "demand": demand.get(e.subject_id, 0),
                    "teachers": ", ".join(t.full_name for t in e.teachers.all())} for e in electives],
        clash_list=[(s, _clash_text(bad)) for s, bad in clash_list[:50]], clash_ids=clash_ids, timetable=timetable,
        timetables=[t for t in school.timetables.all() if t.has_grid], total=school.students.count(),
    ))


def _clash_text(bad):
    from .refs import DAY_SHORT

    return "; ".join(
        f"{DAY_SHORT[d]} {p + 1} ({' + '.join(lesson.subject.short or lesson.subject.name for lesson in ls)})" for d, p, ls in bad
    )


def student_grid(student, timetable):
    school = student.school
    lesson_ids = attendance(school, [student]).get(student.id, set())
    periods = list(school.periods.all())
    days = school.day_names
    cells = defaultdict(list)
    if timetable is not None:
        for card in timetable.cards.filter(day__isnull=False, lesson_id__in=lesson_ids).select_related(
            "lesson__subject", "classroom"
        ).prefetch_related("lesson__teachers"):
            for i in range(card.length):
                cells[(card.day, card.period + i)].append(card)
    rows = [{"period": p, "cells": [cells.get((d, p.index), []) for d in range(len(days))]} for p in periods]
    unplaced = [lesson for lesson in Lesson.objects.filter(id__in=lesson_ids).select_related("subject")
                if timetable is None or not timetable.cards.filter(lesson=lesson, day__isnull=False).exists()]
    return {"days": days, "rows": rows, "unplaced": unplaced}


def student_timetable(request, pk, student_id):
    school = get_object_or_404(School, pk=pk)
    student = get_object_or_404(Student.objects.select_related("school_class"), pk=student_id, school=school)
    timetable = _timetable(school, request)
    from .views import _nav

    return render(request, "timetable/student_timetable.html", _nav(
        school, "students", student=student, timetable=timetable, **student_grid(student, timetable),
    ))
