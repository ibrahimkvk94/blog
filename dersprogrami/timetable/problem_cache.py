"""Çözücü problemi önbelleği (ana görünüm, okul sayfası ve veri listeleri).

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
_school_entries = {}  # okul kimliği → (damga, zaman, problem): derslerden türetilen kartlarla


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


def _school_stamp(school):
    """Veri sürümü + temel tabloların özetleri: yönetim panelinden ya da doğrudan yapılan değişiklikler
    (veri sürümünü artırmayan) da çoğu durumda yakalanır."""
    from .models import Availability, Lesson

    version = School.objects.filter(pk=school.pk).values_list("data_version", flat=True).first()
    lessons = Lesson.objects.filter(school=school).aggregate(n=Count("id"), top=Max("id"), hours=Sum("periods_per_week"))
    avail = Availability.objects.filter(school=school).aggregate(n=Count("id"), top=Max("id"))
    return (school.pk, version, tuple(lessons.values()), tuple(avail.values()),
            school.teachers.count(), school.classes.count(), school.classrooms.count())


def school_problem(school):
    """Okulun güncel verisinden kurulan problem (yükler ve denetim için; yalnızca okunmalı).
    Okul sayfası ve öğretmen/sınıf/ders listeleri her açılışta modeli baştan kurmaz."""
    stamp = _school_stamp(school)
    now = time.monotonic()
    with _lock:
        entry = _school_entries.get(school.pk)
        if entry and entry[0] == stamp and now - entry[1] < MAX_AGE:
            return entry[2]
    problem = build_problem(school)
    with _lock:
        _school_entries[school.pk] = (stamp, now, problem)
        while len(_school_entries) > MAX_ENTRIES:
            _school_entries.pop(min(_school_entries, key=lambda k: _school_entries[k][1]))
    return problem


def invalidate(**kwargs):
    """Okul verisi bu süreçte değişti (yönetim paneli, içe aktarma, kabuk dahil): önbelleği boşalt.
    Başka süreçlerdeki önbellekler veri sürümü (bump) ve MAX_AGE ile yenilenir."""
    with _lock:
        _entries.clear()
        _school_entries.clear()


WATCHED = ("School", "Period", "Building", "Classroom", "Subject", "Teacher", "SchoolClass", "Division", "Group",
           "Lesson", "Availability", "CardRelationship", "Student")


def connect_signals():
    from django.apps import apps
    from django.db.models.signals import m2m_changed, post_delete, post_save

    models = [apps.get_model("timetable", name) for name in WATCHED]
    for model in models:
        post_save.connect(invalidate, sender=model, dispatch_uid=f"problem_cache_save_{model.__name__}")
        post_delete.connect(invalidate, sender=model, dispatch_uid=f"problem_cache_delete_{model.__name__}")
    watched = tuple(models)

    def on_m2m(sender, instance, action, **kwargs):
        if action.startswith("post_") and isinstance(instance, watched):
            invalidate()

    m2m_changed.connect(on_m2m, weak=False, dispatch_uid="problem_cache_m2m")


def bump(school_id):
    School.objects.filter(pk=school_id).update(data_version=F("data_version") + 1)
