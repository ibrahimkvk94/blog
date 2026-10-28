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

def _terms(lesson):
    """Şubenin dönemleri (bit maskesinden); boşsa tüm dönemler = None."""
    mask = lesson.terms_mask
    return None if not mask else {i for i in range(16) if mask >> i & 1}


def student_rules(school):
    """Seçmeli dağıtımında uygulanan kart ilişkileri (öğrenci kuralları)."""
    from .models import CardRelationship

    rules = []
    for rel in school.relationships.filter(active=True, condition__in=CardRelationship.STUDENT).prefetch_related(
        "subjects", "lessons", "subjects_b", "lessons_b", "teachers"
    ):
        rules.append({
            "rel": rel, "cond": rel.condition, "hard": rel.importance == CardRelationship.STRICT, "n": rel.param,
            "a": {x.id for x in rel.subjects.all()} | {x.subject_id for x in rel.lessons.all()},
            "b": {x.id for x in rel.subjects_b.all()} | {x.subject_id for x in rel.lessons_b.all()},
            "teachers": {t.id for t in rel.teachers.all()},
        })
    return rules


def _rule_breaks(rule, subject_id, option, mine, teachers_of):
    """Seçeneğin (şube) kuralı bozup bozmadığı. mine: {ders adı: öğrencinin şubesi}."""
    cond, a, b = rule["cond"], rule["a"], rule["b"]
    mine_teachers = teachers_of[option.id]
    if cond in ("st_same_teacher", "st_diff_teacher") and subject_id in a:
        others = [teachers_of[sec.id] for sid, sec in mine.items() if sid in a and sid != subject_id]
        if cond == "st_same_teacher":
            return any(not (t & mine_teachers) for t in others)
        return any(t & mine_teachers for t in others)
    if cond == "st_teacher_in" and subject_id in a:
        return not (mine_teachers & rule["teachers"])
    if cond == "st_teacher_not_in" and subject_id in a:
        return bool(mine_teachers & rule["teachers"])
    if cond.startswith("st_term") or cond in ("st_same_term", "st_diff_term"):
        if subject_id in a:
            pairs = [(option, sec) for sid, sec in mine.items() if sid in b and sid != subject_id]
        elif subject_id in b:
            pairs = [(sec, option) for sid, sec in mine.items() if sid in a and sid != subject_id]
        else:
            return False
        for sec_a, sec_b in pairs:
            ta, tb = _terms(sec_a), _terms(sec_b)
            if ta is None or tb is None:
                continue
            first_a, first_b = min(ta), min(tb)
            if (cond == "st_term_before" and not first_a < first_b) or (cond == "st_term_before_same" and not first_a <= first_b) \
                    or (cond == "st_same_term" and first_a != first_b) or (cond == "st_diff_term" and first_a == first_b):
                return True
    return False


def distribute(school, timetable=None, reset=False):
    """Öğrencileri seçtikleri ders adlarının seçmeli şubelerine dağıtır.

    Her seçim için: zaten kayıtlıysa korunur (reset değilse); yoksa kontenjanı dolmamış şubeler
    arasından kesin öğrenci kurallarını bozmayanlar alınır; bunlardan öğrencinin programıyla en az
    çakışan, sonra en az yumuşak kural bozan, sonra "aynı şube" arkadaşları en çok olan ve en boş
    şube seçilir. Az şubesi olan seçimler önce dağıtılır.
    Dönüş: {"assigned": n, "kept": n, "unassigned": [(öğrenci, ders adı, neden)]}."""
    lessons = list(school.lessons.filter(elective=True).select_related("subject").prefetch_related("students", "teachers"))
    sections = defaultdict(list)
    for lesson in lessons:
        sections[lesson.subject_id].append(lesson)
    teachers_of = {lesson.id: {t.id for t in lesson.teachers.all()} for lesson in lessons}
    rules = student_rules(school)
    group_rules = [r for r in rules if r["cond"] == "st_same_group"]
    cells = _placed_cells(timetable)
    students = list(school.students.prefetch_related("groups", "choices"))
    with transaction.atomic():
        if reset:
            for lesson in lessons:
                lesson.students.clear()
        members = {lesson.id: set() if reset else {s.id for s in lesson.students.all()} for lesson in lessons}
        mine = defaultdict(dict)  # öğrenci → {ders adı: şube}
        for lesson in lessons:
            for sid in members[lesson.id]:
                mine[sid][lesson.subject_id] = lesson
        base = attendance(school, students)  # seçmeliler dahil mevcut durum
        busy = {}
        for s in students:
            own = base[s.id] - ({lesson.id for lesson in lessons} if reset else set())
            busy[s.id] = Counter(cell for lid in own for cell in cells.get(lid, ()))
        todo = [(s, subject) for s in students for subject in s.choices.all()]
        todo.sort(key=lambda item: (len(sections.get(item[1].id, [])), item[0].id))
        assigned = kept = 0
        unassigned = []

        def peers(s, subject_id, option):
            """"Aynı şube" kuralında öğrencinin diğer seçmelilerdeki şube arkadaşlarından bu şubede olanlar."""
            total = 0
            for rule in group_rules:
                if subject_id not in rule["a"]:
                    continue
                for sid, sec in mine[s.id].items():
                    if sid in rule["a"] and sid != subject_id:
                        total += len((members[sec.id] - {s.id}) & members[option.id])
            return total

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
            hard = [r for r in rules if r["hard"]]
            pending = [c.id for c in s.choices.all() if c.id != subject.id and c.id not in mine[s.id] and sections.get(c.id)]

            def keeps_rest_possible(o):
                """İleriye bakış: bu şube seçilirse öğrencinin bekleyen seçimleri kesin kurallarla hâlâ yerleşebilmeli."""
                trial = {**mine[s.id], subject.id: o}
                return all(
                    any(not any(_rule_breaks(r, other, oo, trial, teachers_of) for r in hard) for oo in sections[other])
                    for other in pending
                )

            allowed = [o for o in free if not any(_rule_breaks(r, subject.id, o, mine[s.id], teachers_of) for r in hard)]
            allowed = [o for o in allowed if keeps_rest_possible(o)] or allowed
            if not allowed:
                broken = next(r["rel"].name for r in rules if r["hard"] and _rule_breaks(r, subject.id, free[0], mine[s.id], teachers_of))
                unassigned.append((s, subject, f"kesin kural nedeniyle uygun şube yok ({broken})"))
                continue
            best = min(allowed, key=lambda o: (
                sum(busy[s.id][c] for c in cells.get(o.id, ())),
                sum(1 for r in rules if not r["hard"] and _rule_breaks(r, subject.id, o, mine[s.id], teachers_of)),
                -peers(s, subject.id, o),
                len(members[o.id]) / (o.capacity or 1000),
                o.id,
            ))
            members[best.id].add(s.id)
            mine[s.id][subject.id] = best
            busy[s.id].update(cells.get(best.id, ()))
            assigned += 1
        for lesson in lessons:
            lesson.students.set(members[lesson.id])
    return {"assigned": assigned, "kept": kept, "unassigned": unassigned}


def rule_warnings(school):
    """Öğrenci kurallarının mevcut seçim ve kayıtlara göre ihlalleri (metin listesi)."""
    rules = student_rules(school)
    if not rules:
        return []
    lessons = list(school.lessons.filter(elective=True).select_related("subject").prefetch_related("students", "teachers"))
    teachers_of = {lesson.id: {t.id for t in lesson.teachers.all()} for lesson in lessons}
    mine = defaultdict(dict)
    for lesson in lessons:
        for st in lesson.students.all():
            mine[st.id][lesson.subject_id] = lesson
    out = []
    for st in school.students.prefetch_related("choices"):
        chosen = {c.id for c in st.choices.all()}
        for rule in rules:
            name = rule["rel"].name
            if rule["cond"] in ("st_min_electives", "st_max_electives"):
                count = len(chosen & rule["a"])
                if rule["cond"] == "st_min_electives" and count < rule["n"]:
                    out.append(f"{st.full_name}: “{name}” – {count} seçim (en az {rule['n']}).")
                if rule["cond"] == "st_max_electives" and count > rule["n"]:
                    out.append(f"{st.full_name}: “{name}” – {count} seçim (en fazla {rule['n']}).")
                continue
            for subject_id, section in mine[st.id].items():
                others = {k: v for k, v in mine[st.id].items() if k != subject_id}
                if _rule_breaks(rule, subject_id, section, others, teachers_of):
                    out.append(f"{st.full_name}: “{name}” kuralı bozuluyor ({section.subject.short or section.subject.name}).")
                    break
    return out


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
    warnings = rule_warnings(school)
    clash_ids = {s.id for s, _ in clash_list}
    from .views import _nav

    return render(request, "timetable/students.html", _nav(
        school, "students", students=students, classes=list(school.classes.all()), class_id=int(class_id) if class_id and class_id.isdigit() else None,
        electives=[{"lesson": e, "count": e.students.count(), "demand": demand.get(e.subject_id, 0),
                    "teachers": ", ".join(t.full_name for t in e.teachers.all())} for e in electives],
        rule_warnings=warnings[:50], rule_warning_count=len(warnings),
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
