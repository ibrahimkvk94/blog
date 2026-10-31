"""Program versiyonları (aSc "Versiyonlar"): elle ve otomatik kayıt, önizleme ve geri yükleme.

Her versiyon kartların konumlarının (gün, saat, derslik, kilit) ve derslerin öğretmen atamalarının anlık
görüntüsüdür (öğretmen havuzu üretimde atamaları değiştirebilir). Program
açılırken ve düzenleme sürerken belirli aralıklarla otomatik versiyon alınır; hatalı bir işlemden
sonra istenen versiyona dönülebilir (dönmeden önce mevcut hal de kaydedilir).
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import Card, Lesson, TimetableVersion

AUTO_INTERVAL = timedelta(minutes=10)


def _state(card):
    return [card.id, card.day, card.period, card.classroom_id, list(card.extra_rooms or []), card.locked]


def current_state(timetable):
    return [_state(c) for c in timetable.cards.order_by("id")]


def current_teachers(timetable):
    """Programdaki kartların dersleri için {ders kimliği (metin): [öğretmen, ...]} (JSON anahtarı metindir)."""
    lessons = timetable.cards.values("lesson_id")  # alt sorgu: uzun kimlik listesi SQLite sınırını aşmasın
    result = {str(l): [] for l in lessons.values_list("lesson_id", flat=True)}
    rows = Lesson.teachers.through.objects.filter(lesson_id__in=lessons).order_by("teacher_id").values_list("lesson_id", "teacher_id")
    for lesson_id, teacher_id in rows:
        result[str(lesson_id)].append(teacher_id)
    return result


def teacher_diff(a, b):
    """Öğretmen ataması farklı dersler (eski sürüm bilgisi yoksa boş)."""
    if not a or not b:
        return set()
    return {k for k in a.keys() & b.keys() if sorted(a[k]) != sorted(b[k])}


def diff_count(a, b):
    """İki anlık görüntü arasında konumu/dersliği/kilidi farklı kart sayısı."""
    old = {row[0]: row[1:] for row in a}
    new = {row[0]: row[1:] for row in b}
    return sum(1 for cid in old.keys() | new.keys() if old.get(cid) != new.get(cid))


def latest(timetable):
    return timetable.versions.order_by("-number").first()


def save_version(timetable, user=None, note="", auto=False, state=None):
    """Versiyon kaydeder. Otomatik kayıt, son versiyondan beri değişiklik yoksa atlanır."""
    state = state if state is not None else current_state(timetable)
    teachers = current_teachers(timetable)
    last = latest(timetable)
    changes = diff_count(last.cards, state) + len(teacher_diff(last.teachers, teachers)) if last else len(state)
    if auto and last is not None and changes == 0:
        return None
    with transaction.atomic():
        number = (last.number + 1) if last else 1
        return TimetableVersion.objects.create(
            timetable=timetable, number=number, user=user if user and user.is_authenticated else None,
            note=note[:200], auto=auto, changes=changes, cards=state, teachers=teachers,
        )


def autosave(timetable, user=None, note="Otomatik kayıt", force=False):
    """Son versiyon AUTO_INTERVAL'den eskiyse (ya da force) mevcut hali otomatik kaydeder."""
    last = latest(timetable)
    if not force and last is not None and timezone.now() - last.created_at < AUTO_INTERVAL:
        return None
    return save_version(timetable, user=user, note=note, auto=True)


def restore(timetable, version, user=None):
    """Programı versiyondaki hale döndürür; önce mevcut hal kaydedilir."""
    from . import editing

    save_version(timetable, user=user, note=f"#{version.number} geri yüklenmeden önce", auto=True)
    cards = {c.id: c for c in timetable.cards.all()}
    target = {row[0]: row for row in version.cards}
    changed = [c for cid, c in cards.items() if cid in target and editing._state(c) != target[cid]]
    editing.record(timetable, f"#{version.number} geri yüklendi", editing.snapshot(changed))
    for card in changed:
        _, card.day, card.period, card.classroom_id, card.extra_rooms, card.locked = target[card.id]
    Card.objects.bulk_update(changed, ["day", "period", "classroom", "extra_rooms", "locked"])
    teachers = _restore_teachers(timetable, version)
    message = f"#{version.number} versiyonuna dönüldü ({len(changed)} kart değişti"
    message += f", {teachers} dersin öğretmeni geri alındı)." if teachers else ")."
    return {"ok": True, "message": message}


def _restore_teachers(timetable, version):
    """Sürümdeki öğretmen atamalarını geri yükler (silinmiş öğretmenler atlanır). Dönüş: değişen ders sayısı."""
    from .models import Teacher
    from .problem_cache import bump

    changed = teacher_diff(current_teachers(timetable), version.teachers)
    if not changed:
        return 0
    valid = set(Teacher.objects.filter(school=timetable.school).values_list("id", flat=True))
    with transaction.atomic():
        for lesson in Lesson.objects.filter(pk__in=[int(k) for k in changed]):
            lesson.teachers.set([t for t in version.teachers[str(lesson.pk)] if t in valid])
    bump(timetable.school_id)
    return len(changed)


def listing(timetable, include_auto=True):
    qs = timetable.versions.select_related("user")
    if not include_auto:
        qs = qs.filter(auto=False)
    return [
        {
            "id": v.id,
            "number": v.number,
            "created": timezone.localtime(v.created_at).strftime("%d.%m.%Y %H:%M"),
            "user": (v.user.get_full_name() or v.user.username) if v.user else "",
            "note": v.note,
            "auto": v.auto,
            "changes": v.changes,
        }
        for v in qs
    ]


def preview(version):
    """Önizleme: sınıf satırları × gün/saat hücreleri, ders adı renkleriyle (aSc versiyon önizlemesi)."""
    timetable = version.timetable
    school = timetable.school
    periods = school.periods.count()
    days = school.days_per_week
    classes = list(school.classes.all())
    cards = {c.id: c for c in timetable.cards.select_related("lesson__subject").prefetch_related("lesson__classes")}
    grid = {cls.id: [None] * (days * periods) for cls in classes}
    for card_id, day, period, *_ in version.cards:
        card = cards.get(card_id)
        if card is None or day is None or period is None:
            continue
        for cls in card.lesson.classes.all():
            for i in range(card.length):
                if cls.id in grid and period + i < periods:
                    grid[cls.id][day * periods + period + i] = card.lesson.subject.color
    return {
        "days": school.day_names,
        "periods": periods,
        "rows": [{"name": cls.short or cls.name, "cells": grid[cls.id]} for cls in classes],
    }
