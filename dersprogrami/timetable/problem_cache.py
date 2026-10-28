"""Ana görünüm için çözücü problemi önbelleği.

Kart seçmek, taşımak ve programı doğrulamak her seferinde problemi veritabanından baştan kurmayı
gerektirmez: kartların yeri problemi değiştirmez. Problem, programın veri sürümü
(School.data_version) ve kart kümesi (kimlikler, kilitler) değişmedikçe yeniden kullanılır.
Veri sürümü, programın verisini değiştiren her başarılı POST'ta artırılır (access.py).
"""

import threading
import time

from django.db.models import Count, F, Max, Q, Sum

from .models import School
from .solver.builder import build_problem

MAX_ENTRIES = 8
MAX_AGE = 600  # güvenlik ağı: yönetim paneli gibi yollardan yapılan değişiklikler için

_lock = threading.Lock()
_entries = {}  # program kimliği → (damga, zaman, problem)


def _stamp(timetable):
    version = School.objects.filter(pk=timetable.school_id).values_list("data_version", flat=True).first()
    cards = timetable.cards.aggregate(
        n=Count("id"), top=Max("id"), total=Sum("id"),
        n_locked=Count("id", filter=Q(locked=True)), locked_ids=Sum("id", filter=Q(locked=True)),
    )
    # Silinen programın kimliği (SQLite'ta) yeniden kullanılabilir: oluşturulma anı da damgada.
    return (timetable.school_id, timetable.created_at, version, cards["n"], cards["top"], cards["total"],
            cards["n_locked"], cards["locked_ids"])


def problem_for(timetable):
    """Programın problemi (yalnızca okunmalı; değiştirecek kod build_problem kullanmalı)."""
    stamp = _stamp(timetable)
    now = time.monotonic()
    with _lock:
        entry = _entries.get(timetable.pk)
        if entry and entry[0] == stamp and now - entry[1] < MAX_AGE:
            return entry[2]
    problem = build_problem(timetable.school, timetable=timetable)
    with _lock:
        _entries[timetable.pk] = (stamp, now, problem)
        while len(_entries) > MAX_ENTRIES:
            _entries.pop(min(_entries, key=lambda k: _entries[k][1]))
    return problem


def bump(school_id):
    School.objects.filter(pk=school_id).update(data_version=F("data_version") + 1)
