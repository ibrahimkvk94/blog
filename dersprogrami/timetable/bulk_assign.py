"""Öğretmen havuzu yardımcıları. Kotalar (ör. TEM100: Ahmet 12, Mehmet 12, Ayşe 11 kısım) kaydedilince
üretimde kilitsiz kısımların öğretmenini çözücü seçer (solver/builder.py, cpsat.teacher_pools). Buradaki
distribute() ise isteğe bağlı ön-dağıtım önizlemesidir: kotaları şu anki programa göre hemen paylaştırır.

Program varsa aynı saate düşen kısımlar aynı öğretmene verilmez; öğretmenin başka dersi olan ya da gelemediği
saatlere düşen kısım ona verilmez. Mevcut atamalar mümkün olduğunca korunur; kalanlar doğal sıradaki
yerlerine göre bloklar halinde dağılır (1–12, 13–24 …). Çok öğretmenli derslere dokunulmaz.
"""

from collections import defaultdict

from ortools.sat.python import cp_model

from .models import Availability, Lesson
from .textsort import natural_key

KEEP, ORDER = 100, 1  # mevcut atamayı koruma ağırlığı, sıra (blok) ağırlığı


class DistributeError(Exception):
    pass


def sections(lessons):
    """Dağıtılabilir kısımlar (en fazla bir öğretmenli), doğal sırada."""
    rows = [l for l in lessons if len(l.teachers.all()) <= 1]
    return sorted(rows, key=lambda l: natural_key(", ".join(c.name for c in l.classes.all()) or "~"))


def _current(lesson):
    teachers = lesson.teachers.all()
    return teachers[0].id if teachers else None


def pool_status(lessons, quotas):
    """Kotalar tutuyor mu? (builder._teacher_pools ile aynı kural) Kilitli kısım öğretmeninin kotasından düşer."""
    rows = sections(lessons)
    locked = [l for l in rows if l.teacher_locked and _current(l) is not None]
    free = len(rows) - len(locked)
    remaining = dict(quotas)
    for lesson in locked:
        if _current(lesson) in remaining:
            remaining[_current(lesson)] -= 1
    over = [t for t, n in remaining.items() if n < 0]
    total = sum(quotas.values())
    ok = not over and sum(remaining.values()) == free
    message = "" if ok else (f"Kotaların toplamı {total}, kısım sayısı {len(rows)}"
                             + (f" ({len(locked)} sabit)" if locked else "") + "; ikisi eşit olmalı"
                             + (" ve sabit kısımlar öğretmenin kotasını aşmamalı" if over else "") + ".")
    return {"ok": ok, "total": total, "sections": len(rows), "locked": len(locked), "free": free, "message": message}


def _timetable(school):
    return school.current_timetable()


def distribute(school, lessons, quotas, use_timetable=True, time_limit=10):
    """lessons: ders adının dersleri; quotas: {öğretmen kimliği: kısım sayısı}.
    Dönüş: ({ders kimliği: öğretmen kimliği}, notlar)."""
    quotas = {t: n for t, n in quotas.items() if n > 0}
    status = pool_status(lessons, quotas)
    if not status["ok"]:
        raise DistributeError(status["message"])
    # Öğretmeni kotada olmayan sabit kısımlar dağıtıma girmez; kotadakiler kendi öğretmeninde kalır
    rows = [l for l in sections(lessons) if not (l.teacher_locked and _current(l) is not None and _current(l) not in quotas)]
    if not rows:
        return {}, []
    ids = {l.id for l in rows}
    notes = []
    cells = defaultdict(set)      # kısım → programdaki hücreleri
    busy = defaultdict(set)       # öğretmen → bu kısımlar dışındaki dolu hücreler
    closed = defaultdict(set)     # öğretmen → gelemediği hücreler
    timetable = _timetable(school) if use_timetable else None
    if timetable is not None:
        lesson_teachers = defaultdict(list)  # büyük programda prefetch yerine tek sorgu (SQLite ifade sınırı)
        for lesson_id, teacher_id in Lesson.teachers.through.objects.filter(
                lesson__school=school, teacher_id__in=list(quotas)).values_list("lesson_id", "teacher_id"):
            lesson_teachers[lesson_id].append(teacher_id)
        for lesson_id, day, period, length in timetable.cards.filter(day__isnull=False).values_list("lesson_id", "day", "period", "length"):
            span = {(day, period + i) for i in range(length)}
            if lesson_id in ids:
                cells[lesson_id] |= span
            else:
                for t in lesson_teachers.get(lesson_id, ()):
                    busy[t] |= span
        for t, d, p in Availability.objects.filter(school=school, teacher_id__in=list(quotas), state=Availability.NO).values_list("teacher_id", "day", "period"):
            closed[t].add((d, p))
        notes.append(f"Saat çakışmaları “{timetable.name}” programına göre önlendi.")

    model = cp_model.CpModel()
    teachers = sorted(quotas)
    x = {}
    for lesson in rows:
        fixed_teacher = _current(lesson) if lesson.teacher_locked else None
        for t in teachers:
            if fixed_teacher is not None and t != fixed_teacher:
                continue  # sabit kısım
            if fixed_teacher is None and cells[lesson.id] & (busy[t] | closed[t]):
                continue  # öğretmen o saatte dolu ya da gelemiyor
            x[lesson.id, t] = model.NewBoolVar(f"x{lesson.id}_{t}")
        options = [x[lesson.id, t] for t in teachers if (lesson.id, t) in x]
        if not options:
            name = ", ".join(c.name for c in lesson.classes.all())
            raise DistributeError(f"{name}: saatlerinde seçilen öğretmenlerin hepsi dolu ya da gelemiyor.")
        model.AddExactlyOne(options)
    for t in teachers:
        model.Add(sum(v for (l, tt), v in x.items() if tt == t) == quotas[t])
        # Aynı saatteki iki kısım aynı öğretmene verilmez
        by_cell = defaultdict(list)
        for lesson in rows:
            if (lesson.id, t) in x:
                for cell in cells[lesson.id]:
                    by_cell[cell].append(x[lesson.id, t])
        for group in by_cell.values():
            if len(group) > 1:
                model.AddAtMostOne(group)
    # Amaç: mevcut atamayı koru, sonra doğal sırada bloklar (öğretmenin bloğunun ortasına yakınlık)
    centers, start = {}, 0
    for t in teachers:
        centers[t] = start + quotas[t] / 2
        start += quotas[t]
    cost = []
    for i, lesson in enumerate(rows):
        current = lesson.teachers.all()[0].id if lesson.teachers.all() else None
        for t in teachers:
            if (lesson.id, t) in x:
                penalty = (0 if current == t else KEEP) + ORDER * int(abs(i + 0.5 - centers[t]))
                cost.append(penalty * x[lesson.id, t])
    model.Minimize(sum(cost))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise DistributeError("Bu kotalarla saat çakışmasız dağıtım yok: aynı saatte okutulan kısım sayısı, o saatte boş "
                              "öğretmen sayısından fazla. Kotaları değiştirin ya da öğretmen ekleyin.")
    result = {l: t for (l, t), v in x.items() if solver.Value(v)}
    kept = sum(1 for lesson in rows if lesson.teachers.all() and result[lesson.id] == lesson.teachers.all()[0].id)
    notes.insert(0, f"{len(rows)} kısım dağıtıldı: {kept} kısmın öğretmeni aynı kalıyor, {len(rows) - kept} kısmınki değişiyor.")
    return result, notes
