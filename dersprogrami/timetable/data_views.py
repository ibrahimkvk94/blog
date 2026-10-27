"""Veri giriş ekranları: okul ve ders saatleri, ders adları, öğretmenler, sınıflar, derslikler,
binalar, dersler (liste, form, sınıf ders tablosu) ve kart ilişkileri."""

import datetime
import json
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from . import forms
from .models import (
    Availability,
    Building,
    CardRelationship,
    Classroom,
    Division,
    Group,
    Lesson,
    Period,
    School,
    SchoolClass,
    Subject,
    Teacher,
)
from .solver.builder import build_problem
from .views import _nav

# --- yardımcılar -------------------------------------------------------------------------------


def loads(school):
    """Öğretmen ve sınıf yükleri: (haftalık saat, uygun hücre sayısı)."""
    problem = build_problem(school)
    teacher = defaultdict(int)
    atom = defaultdict(int)
    for card in problem.cards:
        for t in card.teachers:
            teacher[t] += card.length
        for a in card.atoms:
            atom[a] += card.length
    classes = defaultdict(int)
    for atom_id, hours in atom.items():
        class_id = int(atom_id.split("|")[0])
        classes[class_id] = max(classes[class_id], hours)
    cells = problem.days * problem.periods
    return (
        {t: (h, problem.teacher_available.get(t, cells)) for t, h in teacher.items()},
        {c: (h, next((problem.atom_available[a] for a in problem.atom_available if a.startswith(f"{c}|")), cells)) for c, h in classes.items()},
    )


def _load_badge(value):
    if not value:
        return format_html('<span class="subtle">–</span>')
    hours, free = value
    css = "failed" if hours > free else "ok" if hours else ""
    return format_html('<span class="pill {}">{} / {} saat</span>', css, hours, free)


def _teacher_name(t):
    return f"{t.first_name} {t.last_name}"


# --- genel kayıt tanımları ---------------------------------------------------------------------


@dataclass
class Entity:
    slug: str
    model: type
    form: type
    title: str
    singular: str
    columns: list
    availability: str | None = None
    order: tuple = ()
    help: str = ""
    prefetch: tuple = field(default_factory=tuple)


def _swatch(subject, ctx=None):
    return format_html('<span class="swatch" style="background:{}"></span> {}', subject.color, subject.name)


ENTITIES = {
    "ders-adlari": Entity(
        "ders-adlari", Subject, forms.SubjectForm, "Ders adları", "Ders adı",
        [("Ad", _swatch), ("Kısa ad", lambda s, ctx: s.short), ("Ders sayısı", lambda s, ctx: s.n_lessons)],
        availability="subject", order=("name",),
        help="Ders adının müsaitliği, bu adı taşıyan tüm dersler için geçerlidir (ör. Beden Eğitimi son saatte olmasın).",
    ),
    "ogretmenler": Entity(
        "ogretmenler", Teacher, forms.TeacherForm, "Öğretmenler", "Öğretmen",
        [
            ("Ad soyad", lambda t, ctx: _teacher_name(t)),
            ("Kısa ad", lambda t, ctx: t.short),
            ("Haftalık yük", lambda t, ctx: _load_badge(ctx["teacher_loads"].get(t.id))),
            ("Sınırlar", lambda t, ctx: " · ".join(filter(None, [
                f"günde ≤{t.max_periods_per_day}" if t.max_periods_per_day else "",
                f"haftada ≤{t.max_days_per_week} gün" if t.max_days_per_week else "",
                f"boşluk ≤{t.max_gaps_per_week}/hafta" if t.max_gaps_per_week is not None else "",
            ])) or "–"),
        ],
        availability="teacher", order=("last_name", "first_name"),
    ),
    "siniflar": Entity(
        "siniflar", SchoolClass, forms.SchoolClassForm, "Sınıflar", "Sınıf",
        [
            ("Sınıf", lambda c, ctx: c.name),
            ("Seviye", lambda c, ctx: c.grade or "–"),
            ("Sınıf dersliği", lambda c, ctx: c.home_classroom or "–"),
            ("Bölünmeler", lambda c, ctx: "; ".join(f"{d.name}: {', '.join(g.name for g in d.groups.all())}" for d in c.divisions.all()) or "–"),
            ("Haftalık yük", lambda c, ctx: _load_badge(ctx["class_loads"].get(c.id))),
        ],
        availability="school_class", order=("grade", "name"), prefetch=("divisions__groups",),
    ),
    "derslikler": Entity(
        "derslikler", Classroom, forms.ClassroomForm, "Derslikler", "Derslik",
        [("Ad", lambda r, ctx: r.name), ("Kısa ad", lambda r, ctx: r.short), ("Kapasite", lambda r, ctx: r.capacity or "–"), ("Bina", lambda r, ctx: r.building or "–")],
        availability="classroom", order=("name",),
    ),
    "binalar": Entity(
        "binalar", Building, forms.BuildingForm, "Binalar", "Bina",
        [("Ad", lambda b, ctx: b.name)], order=("name",),
    ),
    "kart-iliskileri": Entity(
        "kart-iliskileri", CardRelationship, forms.RelationshipForm, "Kart ilişkileri", "Kart ilişkisi",
        [
            ("Ad", lambda r, ctx: r.name),
            ("Koşul", lambda r, ctx: r.get_condition_display() + (f" (N={r.param})" if r.condition in (r.MAX_PER_DAY, r.MAX_CONSECUTIVE) else "")),
            ("Uygula", lambda r, ctx: r.get_apply_to_display()),
            ("Önem", lambda r, ctx: r.get_importance_display()),
            ("Durum", lambda r, ctx: format_html('<span class="pill {}">{}</span>', "ok" if r.active else "", "Etkin" if r.active else "Kapalı")),
        ],
        order=("name",),
        help="Seçilen kartlara toplu kural uygular: ör. “her sınıfta sayısal derslerden günde en fazla 2 kart”.",
    ),
}


def _entity(slug):
    try:
        return ENTITIES[slug]
    except KeyError:
        raise Http404


def _school(pk):
    return get_object_or_404(School, pk=pk)


def entity_list(request, pk, slug):
    school, entity = _school(pk), _entity(slug)
    qs = entity.model.objects.filter(school=school).order_by(*entity.order).prefetch_related(*entity.prefetch)
    if entity.model is Subject:
        qs = qs.annotate(n_lessons=Count("lesson"))
    ctx = {}
    if entity.model in (Teacher, SchoolClass):
        ctx["teacher_loads"], ctx["class_loads"] = loads(school)
    rows = [{"obj": obj, "cells": [fn(obj, ctx) for _, fn in entity.columns]} for obj in qs]
    return render(
        request,
        "timetable/data/list.html",
        _nav(school, "data", data_nav=slug, entity=entity, headers=[h for h, _ in entity.columns], rows=rows),
    )


def _availability_grid(school, entity, obj):
    states = {}
    if obj is not None and entity.availability:
        for a in Availability.objects.filter(**{entity.availability: obj}):
            states[f"{a.day}-{a.period}"] = a.state
    return {
        "days": school.day_names,
        "periods": [{"name": p.name, "start": p.start_time.strftime("%H:%M") if p.start_time else ""} for p in school.periods.all()],
        "states": states,
    }


def _save_availability(school, field, obj, raw):
    try:
        states = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return
    Availability.objects.filter(**{field: obj}).delete()
    rows = []
    for key, state in states.items():
        if state not in (Availability.NO, Availability.MAYBE):
            continue
        try:
            day, period = (int(x) for x in key.split("-"))
        except ValueError:
            continue
        if day < school.days_per_week and period < school.periods.count():
            rows.append(Availability(school=school, day=day, period=period, state=state, **{field: obj}))
    Availability.objects.bulk_create(rows)


def _division_rows(cls):
    if cls is None:
        return []
    return [
        {"id": d.id, "name": d.name, "groups": [{"id": g.id, "name": g.name} for g in d.groups.all()]}
        for d in cls.divisions.prefetch_related("groups")
    ]


def _save_divisions(cls, raw):
    """Bölünme/grup düzenleyicisinden gelen JSON'u kaydeder; kimliği korunan gruplar derslerde kalır."""
    try:
        rows = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return
    existing = {d.id: d for d in cls.divisions.prefetch_related("groups")}
    kept = set()
    for row in rows:
        names = [g.get("name", "").strip() for g in row.get("groups", [])]
        if not row.get("name", "").strip() or len([n for n in names if n]) < 2:
            continue  # bölünme sınıfı en az iki gruba ayırmalı
        division = existing.get(row.get("id"))
        if division is None:
            division = Division.objects.create(school_class=cls, name=row["name"].strip())
        elif division.name != row["name"].strip():
            division.name = row["name"].strip()
            division.save(update_fields=["name"])
        kept.add(division.id)
        groups = {g.id: g for g in division.groups.all()}
        kept_groups = set()
        for item in row.get("groups", []):
            name = item.get("name", "").strip()
            if not name:
                continue
            group = groups.get(item.get("id"))
            if group is None:
                group = Group.objects.create(division=division, name=name)
            elif group.name != name:
                group.name = name
                group.save(update_fields=["name"])
            kept_groups.add(group.id)
        Group.objects.filter(division=division).exclude(id__in=kept_groups).delete()
    Division.objects.filter(school_class=cls).exclude(id__in=kept).delete()


def entity_edit(request, pk, slug, obj_id=None):
    school, entity = _school(pk), _entity(slug)
    obj = get_object_or_404(entity.model, pk=obj_id, school=school) if obj_id else None
    form = entity.form(request.POST or None, instance=obj, school=school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            obj = form.save()
            if entity.availability:
                _save_availability(school, entity.availability, obj, request.POST.get("availability"))
            if entity.model is SchoolClass:
                _save_divisions(obj, request.POST.get("divisions"))
        messages.success(request, f"{entity.singular} kaydedildi: {obj}")
        if request.POST.get("next") == "new":
            return redirect("timetable:data_new", pk=school.pk, slug=slug)
        return redirect("timetable:data_list", pk=school.pk, slug=slug)

    impact = ""
    if obj is not None:
        impact = _delete_impact(obj)
    return render(
        request,
        "timetable/data/form.html",
        _nav(
            school,
            "data",
            data_nav=slug,
            entity=entity,
            obj=obj,
            form=form,
            impact=impact,
            availability=_availability_grid(school, entity, obj) if entity.availability else None,
            divisions=_division_rows(obj) if entity.model is SchoolClass else None,
        ),
    )


def _delete_impact(obj):
    if isinstance(obj, Subject):
        n = Lesson.objects.filter(subject=obj).count()
        return f"Bu ders adını kullanan {n} ders de silinecek." if n else ""
    if isinstance(obj, SchoolClass):
        n = Lesson.objects.annotate(nc=Count("classes")).filter(classes=obj, nc=1).count()
        return f"Yalnızca bu sınıfa ait {n} ders de silinecek." if n else ""
    if isinstance(obj, Teacher):
        n = obj.lessons.count()
        return f"Öğretmen {n} dersten çıkarılacak." if n else ""
    return ""


@require_POST
def entity_delete(request, pk, slug, obj_id):
    school, entity = _school(pk), _entity(slug)
    obj = get_object_or_404(entity.model, pk=obj_id, school=school)
    with transaction.atomic():
        if isinstance(obj, SchoolClass):
            Lesson.objects.annotate(nc=Count("classes")).filter(classes=obj, nc=1).delete()
        name = str(obj)
        obj.delete()
    messages.success(request, f"{entity.singular} silindi: {name}")
    return redirect("timetable:data_list", pk=school.pk, slug=slug)


# --- okul ve ders saatleri ---------------------------------------------------------------------


def default_periods(school, count=8, start=datetime.time(8, 30), length=40, short_break=10, lunch_after=5, lunch=50):
    current = datetime.datetime.combine(datetime.date.today(), start)
    for i in range(count):
        end = current + datetime.timedelta(minutes=length)
        Period.objects.create(school=school, index=i, name=f"{i + 1}. saat", start_time=current.time(), end_time=end.time())
        current = end + datetime.timedelta(minutes=lunch if i + 1 == lunch_after else short_break)


def school_create(request):
    form = forms.SchoolForm(request.POST or None, initial={"days_per_week": 5})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            school = form.save()
            default_periods(school)
        messages.success(request, "Okul oluşturuldu. Ders saatlerini kontrol edip ders adlarını girerek başlayın.")
        return redirect("timetable:school_settings", pk=school.pk)
    return render(request, "timetable/data/settings.html", {"form": form, "formset": None, "creating": True})


def school_settings(request, pk):
    school = _school(pk)
    form = forms.SchoolForm(request.POST or None, instance=school)
    formset = forms.PeriodFormSet(request.POST or None, queryset=school.periods.all(), prefix="periods")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        kept = [f for f in formset.forms if f.has_changed() or f.instance.pk]
        kept = [f for f in kept if not (formset.can_delete and formset._should_delete_form(f))]
        if not kept:
            messages.error(request, "En az bir ders saati olmalı.")
        else:
            with transaction.atomic():
                form.save()
                for f in formset.deleted_forms:
                    if f.instance.pk:
                        f.instance.delete()
                # Sıra numaraları çakışmasın diye önce geçici değer, sonra gerçek sıra.
                for i, f in enumerate(kept):
                    if f.instance.pk:
                        Period.objects.filter(pk=f.instance.pk).update(index=1000 + i)
                for i, f in enumerate(kept):
                    period = f.save(commit=False)
                    period.school = school
                    period.index = i
                    if not period.name:
                        period.name = f"{i + 1}. saat"
                    period.save()
            messages.success(request, "Okul ayarları ve ders saatleri kaydedildi.")
            return redirect("timetable:school_settings", pk=school.pk)
    return render(
        request,
        "timetable/data/settings.html",
        _nav(school, "data", data_nav="okul", form=form, formset=formset, creating=False),
    )


# --- dersler -----------------------------------------------------------------------------------


def _lesson_rows(lessons):
    rows = []
    for lesson in lessons:
        lengths = lesson.card_lengths()
        pattern = "+".join(str(n) for n in lengths) if len(lengths) > 1 and lesson.card_length > 1 else ""
        rows.append(
            {
                "lesson": lesson,
                "classes": ", ".join(c.name for c in lesson.classes.all()),
                "groups": ", ".join(sorted({g.name for g in lesson.groups.all()})),
                "teachers": ", ".join(_teacher_name(t) for t in lesson.teachers.all()),
                "rooms": ", ".join(str(r) for r in lesson.classrooms.all()),
                "pattern": pattern,
            }
        )
    return rows


def lessons(request, pk):
    school = _school(pk)
    qs = (
        Lesson.objects.filter(school=school)
        .select_related("subject")
        .prefetch_related("classes", "groups", "teachers", "classrooms")
        .order_by("subject__name", "id")
    )
    class_id, teacher_id, query = request.GET.get("sinif"), request.GET.get("ogretmen"), request.GET.get("q", "").strip()
    if class_id:
        qs = qs.filter(classes__id=class_id)
    if teacher_id:
        qs = qs.filter(teachers__id=teacher_id)
    if query:
        qs = qs.filter(Q(subject__name__icontains=query) | Q(subject__short__icontains=query))
    qs = qs.distinct()
    teacher_loads, class_loads = loads(school)
    classes = list(school.classes.all())
    return render(
        request,
        "timetable/data/lessons.html",
        _nav(
            school,
            "data",
            data_nav="dersler",
            rows=_lesson_rows(qs),
            classes=classes,
            teachers=list(school.teachers.all()),
            class_loads=[(c, class_loads.get(c.id, (0, school.days_per_week * school.periods.count()))) for c in classes],
            teacher_loads=teacher_loads,
            filters={"sinif": class_id or "", "ogretmen": teacher_id or "", "q": query},
            total=sum(lesson.periods_per_week for lesson in qs),
        ),
    )


def lesson_edit(request, pk, lesson_id=None):
    school = _school(pk)
    lesson = get_object_or_404(Lesson, pk=lesson_id, school=school) if lesson_id else None
    initial = {}
    if lesson is None and request.GET.get("sinif"):
        initial["classes"] = [request.GET["sinif"]]
    form = forms.LessonForm(request.POST or None, instance=lesson, school=school, initial=initial)
    if request.method == "POST" and form.is_valid():
        lesson = form.save()
        messages.success(request, f"Ders kaydedildi: {lesson}")
        if request.POST.get("next") == "new":
            return redirect(reverse("timetable:lesson_new", args=[school.pk]) + "?" + "&".join(f"sinif={c.pk}" for c in lesson.classes.all()[:1]))
        back = request.POST.get("back") or ""
        if back.startswith("/"):
            return redirect(back)
        return redirect("timetable:lessons", pk=school.pk)
    return render(
        request,
        "timetable/data/lesson_form.html",
        _nav(school, "data", data_nav="dersler", form=form, lesson=lesson, back=request.GET.get("back", "")),
    )


@require_POST
def lesson_delete(request, pk, lesson_id):
    school = _school(pk)
    lesson = get_object_or_404(Lesson, pk=lesson_id, school=school)
    name = str(lesson)
    lesson.delete()
    messages.success(request, f"Ders silindi: {name}")
    back = request.POST.get("back") or ""
    return redirect(back if back.startswith("/") else reverse("timetable:lessons", args=[school.pk]))


def _is_simple(lesson):
    return lesson.classes.count() == 1 and not lesson.groups.exists() and lesson.teachers.count() <= 1 and lesson.classrooms.count() <= 1


def class_lessons(request, pk, class_id):
    """Bir sınıfın tek öğretmenli, grupsuz derslerini tek tabloda hızlıca girme."""
    school = _school(pk)
    cls = get_object_or_404(SchoolClass, pk=class_id, school=school)
    subjects = list(school.subjects.order_by("name"))
    class_lessons_qs = list(
        Lesson.objects.filter(classes=cls).select_related("subject").prefetch_related("classes", "groups", "teachers", "classrooms")
    )
    simple = {}
    others = []
    for lesson in class_lessons_qs:
        if _is_simple(lesson) and lesson.subject_id not in simple:
            simple[lesson.subject_id] = lesson
        else:
            others.append(lesson)

    if request.method == "POST":
        teachers = {t.id: t for t in school.teachers.all()}
        rooms = {r.id: r for r in school.classrooms.all()}
        created = updated = deleted = 0
        with transaction.atomic():
            for subject in subjects:
                raw = request.POST.get(f"hours-{subject.id}", "").strip()
                hours = int(raw) if raw.isdigit() else 0
                lesson = simple.get(subject.id)
                if hours <= 0:
                    if lesson is not None:
                        lesson.delete()
                        deleted += 1
                    continue
                length = request.POST.get(f"length-{subject.id}", "1")
                length = int(length) if length.isdigit() and 1 <= int(length) <= 4 else 1
                teacher = teachers.get(int(request.POST.get(f"teacher-{subject.id}") or 0))
                room = rooms.get(int(request.POST.get(f"room-{subject.id}") or 0))
                if lesson is None:
                    lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=hours, card_length=length)
                    lesson.classes.set([cls])
                    created += 1
                else:
                    lesson.periods_per_week, lesson.card_length = hours, length
                    lesson.save(update_fields=["periods_per_week", "card_length"])
                    updated += 1
                lesson.teachers.set([teacher] if teacher else [])
                lesson.classrooms.set([room] if room else [])
        messages.success(request, f"{cls} ders tablosu kaydedildi: {created} yeni, {updated} güncellenen, {deleted} silinen ders.")
        return redirect("timetable:class_lessons", pk=school.pk, class_id=cls.pk)

    other_by_subject = defaultdict(int)
    for lesson in others:
        other_by_subject[lesson.subject_id] += lesson.periods_per_week
    rows = []
    for subject in subjects:
        lesson = simple.get(subject.id)
        rows.append(
            {
                "subject": subject,
                "other_hours": other_by_subject.get(subject.id, 0),
                "hours": lesson.periods_per_week if lesson else "",
                "length": lesson.card_length if lesson else 1,
                "teacher": (lesson.teachers.first().id if lesson and lesson.teachers.exists() else None),
                "room": (lesson.classrooms.first().id if lesson and lesson.classrooms.exists() else None),
            }
        )
    # Başka sınıftan kopyalamak için diğer sınıfların basit dersleri: {sınıf: {ders adı: [saat, uzunluk]}}
    copy_source = defaultdict(dict)
    for lesson in Lesson.objects.filter(school=school).prefetch_related("classes", "groups", "teachers", "classrooms"):
        if _is_simple(lesson):
            copy_source[lesson.classes.first().id].setdefault(lesson.subject_id, [lesson.periods_per_week, lesson.card_length])
    other_hours = sum(lesson.periods_per_week for lesson in others)
    # Toplam yükte grup dersleri bir kez sayılsın: gerçek sınıf yükünden tek öğretmenli dersleri düş.
    class_total = loads(school)[1].get(cls.pk, (0, 0))[0]
    other_effective = max(0, class_total - sum(lesson.periods_per_week for lesson in simple.values()))
    return render(
        request,
        "timetable/data/class_lessons.html",
        _nav(
            school,
            "data",
            data_nav="dersler",
            cls=cls,
            rows=rows,
            others=_lesson_rows(others),
            other_hours=other_hours,
            other_effective=other_effective,
            classes=[c for c in school.classes.all() if c.pk != cls.pk],
            all_classes=list(school.classes.all()),
            teachers=list(school.teachers.all()),
            rooms=list(school.classrooms.all()),
            capacity=school.days_per_week * school.periods.count(),
            copy_source={str(k): v for k, v in copy_source.items() if k != cls.pk},
        ),
    )
