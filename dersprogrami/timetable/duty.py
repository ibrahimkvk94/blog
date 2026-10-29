"""Nöbet çizelgesi (aSc 29. bölüm "Room supervision" karşılığı; Türk okullarındaki günlük nöbet).

Her nöbet yeri için her gün belirli sayıda öğretmen gerekir. Dağıtım küçük bir CP-SAT modeliyle
yapılır:
- sert: muaf öğretmen nöbet tutmaz; öğretmen o gün tamamen kapalıysa nöbet tutmaz; bir öğretmen
  bir günde en fazla bir yerde nöbet tutar; her yerin her günü tam doldurulur.
- yumuşak: öğretmen haftalık sınırını aşmasın (aşarsa büyük ceza), dersinin olmadığı gün nöbet
  tutmasın, nöbetler öğretmenler arasında eşit dağılsın, dersi çok olan gün tercih edilsin.
"""

from collections import defaultdict

from django.db import transaction
from ortools.sat.python import cp_model

from .models import Availability, Duty, Lesson

W_OVER_LIMIT = 1000
W_NO_LESSON_DAY = 60
W_IMBALANCE = 20
W_FEW_LESSONS = 2


def teacher_days(school, timetable):
    """Öğretmen → {gün: o gün ders saati sayısı} (yayındaki programdan)."""
    result = defaultdict(lambda: defaultdict(int))
    if timetable is None:
        return result
    # Ders–öğretmen eşleşmesi ara tablodan tek sorguyla (büyük okulda prefetch SQLite sınırını aşar).
    teachers = defaultdict(list)
    for lesson_id, teacher_id in Lesson.teachers.through.objects.filter(lesson__school=school).values_list("lesson_id", "teacher_id"):
        teachers[lesson_id].append(teacher_id)
    for lesson_id, day, length in timetable.cards.filter(day__isnull=False).values_list("lesson_id", "day", "length"):
        for teacher_id in teachers[lesson_id]:
            result[teacher_id][day] += length
    return result


def closed_days(school):
    """Öğretmen → tamamen kapalı (müsait olmayan) günler."""
    periods = school.periods.count()
    blocked = defaultdict(lambda: defaultdict(int))
    for a in Availability.objects.filter(school=school, teacher__isnull=False, state=Availability.NO):
        blocked[a.teacher_id][a.day] += 1
    return {t: {d for d, n in days.items() if n >= periods} for t, days in blocked.items()}


def generate(school, timetable=None, time_limit=10):
    """Nöbetleri yeniden dağıtır. Dönüş: {"ok", "message", "assigned", "missing"}."""
    timetable = timetable or school.active_timetable or school.timetables.filter(status__in=["ok", "partial"]).first()
    places = list(school.duty_places.all())
    if not places:
        return {"ok": False, "message": "Önce en az bir nöbet yeri ekleyin."}
    teachers = [t for t in school.teachers.all() if not t.duty_exempt]
    if not teachers:
        return {"ok": False, "message": "Nöbet tutabilecek öğretmen yok."}
    lessons = teacher_days(school, timetable)
    closed = closed_days(school)
    default_limit = school.duties_per_teacher

    m = cp_model.CpModel()
    x = {}
    for place in places:
        for d in place.active_days():
            for t in teachers:
                if d not in closed.get(t.id, set()):
                    x[(t.id, place.id, d)] = m.NewBoolVar(f"x{t.id}_{place.id}_{d}")
    missing = []
    for place in places:
        for d in place.active_days():
            options = [x[k] for k in x if k[1] == place.id and k[2] == d]
            need = min(place.teachers_per_day, len(options))
            if need < place.teachers_per_day:
                missing.append(f"{place.name} – {school.day_names[d]}")
            m.Add(sum(options) == need)
    penalties = []
    loads = {}
    for t in teachers:
        mine = [v for k, v in x.items() if k[0] == t.id]
        for d in range(school.days_per_week):
            same_day = [v for k, v in x.items() if k[0] == t.id and k[2] == d]
            if len(same_day) > 1:
                m.Add(sum(same_day) <= 1)
            hours = lessons.get(t.id, {}).get(d, 0)
            for v in same_day:
                if timetable is not None and hours == 0:
                    penalties.append(W_NO_LESSON_DAY * v)
                else:
                    penalties.append(W_FEW_LESSONS * max(0, 6 - hours) * v)
        limit = t.max_duties if t.max_duties is not None else default_limit
        load = m.NewIntVar(0, len(mine), f"load{t.id}")
        m.Add(load == sum(mine))
        over = m.NewIntVar(0, len(mine), f"over{t.id}")
        m.Add(over >= load - limit)
        penalties.append(W_OVER_LIMIT * over)
        loads[t.id] = load
    if loads:
        top = m.NewIntVar(0, len(places) * school.days_per_week, "top")
        bottom = m.NewIntVar(0, len(places) * school.days_per_week, "bottom")
        for load in loads.values():
            m.Add(top >= load)
            m.Add(bottom <= load)
        penalties.append(W_IMBALANCE * (top - bottom))
    m.Minimize(sum(penalties))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"ok": False, "message": "Nöbet dağıtılamadı: günlük nöbetçi sayısı öğretmen sayısını aşıyor olabilir."}
    with transaction.atomic():
        Duty.objects.filter(place__school=school).delete()
        Duty.objects.bulk_create(
            Duty(place_id=place_id, day=d, teacher_id=t_id) for (t_id, place_id, d), v in x.items() if solver.Value(v)
        )
    assigned = sum(1 for v in x.values() if solver.Value(v))
    over = [t for t in teachers if solver.Value(loads[t.id]) > (t.max_duties if t.max_duties is not None else default_limit)]
    message = f"{assigned} nöbet dağıtıldı."
    if over:
        message += f" {len(over)} öğretmene haftalık sınırın üzerinde nöbet verildi (nöbet yeri/gün sayısı fazla)."
    if missing:
        message += " Doldurulamayan: " + ", ".join(missing[:5]) + "."
    return {"ok": True, "message": message, "assigned": assigned, "missing": missing}


def roster(school, timetable=None):
    """Çizelge görünümü için: yerler × günler hücreleri ve öğretmen özetleri."""
    timetable = timetable or school.active_timetable or school.timetables.filter(status__in=["ok", "partial"]).first()
    places = list(school.duty_places.all())
    duties = list(Duty.objects.filter(place__school=school).select_related("teacher"))
    lessons = teacher_days(school, timetable)
    closed = closed_days(school)
    cells = defaultdict(list)
    for duty in duties:
        cells[(duty.place_id, duty.day)].append(duty)
    rows = []
    for place in places:
        active = set(place.active_days())
        rows.append({
            "place": place,
            "cells": [
                {"day": d, "name": school.day_names[d], "active": d in active, "duties": cells.get((place.id, d), []),
                 "missing": max(0, place.teachers_per_day - len(cells.get((place.id, d), []))) if d in active else 0}
                for d in range(school.days_per_week)
            ],
        })
    counts = defaultdict(int)
    warnings = []
    for duty in duties:
        counts[duty.teacher_id] += 1
        if timetable is not None and not lessons.get(duty.teacher_id, {}).get(duty.day):
            warnings.append(f"{duty.teacher.full_name}: {school.day_names[duty.day]} günü dersi yok ama nöbetçi ({duty.place}).")
        if duty.day in closed.get(duty.teacher_id, set()):
            warnings.append(f"{duty.teacher.full_name}: {school.day_names[duty.day]} günü müsait değil ama nöbetçi.")
    same_day = defaultdict(list)
    for duty in duties:
        same_day[(duty.teacher_id, duty.day)].append(duty)
    for (t_id, d), items in same_day.items():
        if len(items) > 1:
            warnings.append(f"{items[0].teacher.full_name}: {school.day_names[d]} günü {len(items)} yerde nöbetçi.")
    teachers = []
    for t in school.teachers.all():
        limit = t.max_duties if t.max_duties is not None else school.duties_per_teacher
        teachers.append({
            "teacher": t,
            "count": counts.get(t.id, 0),
            "limit": 0 if t.duty_exempt else limit,
            "exempt": t.duty_exempt,
            "lesson_days": [lessons.get(t.id, {}).get(d, 0) for d in range(school.days_per_week)],
        })
    return {"rows": rows, "teachers": teachers, "warnings": warnings, "timetable": timetable, "days": school.day_names}


def is_on_duty(school, teacher_id, day):
    return Duty.objects.filter(place__school=school, teacher_id=teacher_id, day=day).exists()
