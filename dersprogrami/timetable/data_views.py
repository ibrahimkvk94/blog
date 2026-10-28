"""Veri giriş ekranları: okul ve ders saatleri, ders adları, öğretmenler, sınıflar, derslikler,
binalar, dersler (liste, form, sınıf ders tablosu) ve kart ilişkileri."""

import datetime
import json
from urllib.parse import urlencode
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import format_html
from django.views.decorators.http import require_POST

from . import forms, importer
from .textsort import natural_key
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
from .views import _nav

# --- yardımcılar -------------------------------------------------------------------------------


def loads(school):
    """Öğretmen ve sınıf yükleri: (haftalık saat, uygun hücre sayısı)."""
    from .problem_cache import school_problem

    problem = school_problem(school)
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


def _target_badge(teacher, ctx):
    """Öğretmenin ders yükü hedefine göre eksik/fazla saat."""
    if not teacher.target_periods:
        return format_html('<span class="subtle">–</span>')
    hours = (ctx["teacher_loads"].get(teacher.id) or (0, 0))[0]
    diff = hours - teacher.target_periods
    if diff == 0:
        return format_html('<span class="pill ok">{} saat ✓</span>', teacher.target_periods)
    css = "warn" if diff < 0 else "failed"
    return format_html('<span class="pill {}">{} saat ({})</span>', css, teacher.target_periods, f"{diff:+d}")


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
    # Düzenleme ekranı: sekmeler → bölümler → alanlar. Tanımsız alanlar ilk bölüme eklenir.
    tabs: tuple = ()
    # Liste ve gezinme: doğal sıralama anahtarı, gezinme satırının adı ve alt bilgisi
    sort: object = None
    nav_label: object = None
    nav_sub: object = None


def _divisions_cell(cls):
    divisions = list(cls.divisions.all())
    if not divisions:
        return format_html('<span class="subtle">–</span>')
    full = "; ".join(f"{d.name}: {', '.join(g.name for g in d.groups.all())}" for d in divisions)
    groups = sum(len(d.groups.all()) for d in divisions)
    return format_html('<span title="{}">{} bölünme · {} grup</span>', full, len(divisions), groups)


def _hours(n):
    return f"{n} saat" if n else ""


def _swatch(subject, ctx=None):
    return format_html('<span class="swatch" style="background:{}"></span> {}', subject.color, subject.name)


ENTITIES = {
    "ders-adlari": Entity(
        "ders-adlari", Subject, forms.SubjectForm, "Ders adları", "Ders adı",
        [
            ("Ad", _swatch), ("Kısa ad", lambda s, ctx: s.short), ("Ders sayısı", lambda s, ctx: s.n_lessons),
            ("Varsayılan derslik", lambda s, ctx: ", ".join(str(r) for r in s.classrooms.all()) or "–"),
        ],
        availability="subject", order=("name",), prefetch=("classrooms",),
        tabs=(("genel", "Genel", (
            ("Ders adı", "Programda ve çıktılarda görünen ad, kısa ad ve renk.", ("name", "short", "color")),
            ("Derslik", "Bu adı taşıyan derslerde derslik seçilmemişse kullanılır.", ("classrooms",)),
        )),),
        nav_sub=lambda s, ctx: s.short,
        help="Ders adının müsaitliği, bu adı taşıyan tüm dersler için geçerlidir (ör. Beden Eğitimi son saatte olmasın).",
    ),
    "ogretmenler": Entity(
        "ogretmenler", Teacher, forms.TeacherForm, "Öğretmenler", "Öğretmen",
        [
            ("Ad soyad", lambda t, ctx: _teacher_name(t)),
            ("Kısa ad", lambda t, ctx: t.short),
            ("Haftalık yük", lambda t, ctx: _load_badge(ctx["teacher_loads"].get(t.id))),
            ("Hedef yük", _target_badge),
            ("Branş", lambda t, ctx: ", ".join(s.short or s.name for s in t.subjects.all()) or "–"),
            ("Sınırlar", lambda t, ctx: " · ".join(filter(None, [
                f"günde ≤{t.max_periods_per_day}" if t.max_periods_per_day else "",
                f"haftada ≤{t.max_days_per_week} gün" if t.max_days_per_week else "",
                f"boşluk ≤{t.max_gaps_per_week}/hafta" if t.max_gaps_per_week is not None else "",
            ])) or "–"),
        ],
        availability="teacher", order=("last_name", "first_name"), prefetch=("subjects",),
        tabs=(
            ("genel", "Genel", (
                ("Kimlik", "Ad, kısa ad ve raporlarda adın önüne yazılabilen künye.", ("first_name", "last_name", "short", "department", "title")),
                ("Görev", "Ders yükü hedefi, branşlar ve öğretmenin dersliği.", ("target_periods", "home_classroom", "subjects")),
                ("İletişim ve ÜYBS", "Bildirimler ve ÜYBS aktarımı için.", ("email", "tc_no")),
            )),
            ("kisitlar", "Kısıtlar", (
                ("Günlük", "Boş bırakılan alan sınır koymaz.", ("max_periods_per_day", "min_periods_per_day", "max_consecutive", "max_gaps_per_day")),
                ("Haftalık", "", ("max_days_per_week", "max_gaps_per_week")),
                ("Nöbet", "", ("duty_exempt", "max_duties")),
            )),
        ),
        sort=lambda t: natural_key(f"{t.first_name} {t.last_name}"),
        nav_label=lambda t, ctx: _teacher_name(t),
        nav_sub=lambda t, ctx: " · ".join(filter(None, [t.department, t.title, _hours((ctx["teacher_loads"].get(t.id) or (0, 0))[0])])),
    ),
    "siniflar": Entity(
        "siniflar", SchoolClass, forms.SchoolClassForm, "Sınıflar", "Sınıf",
        [
            ("Sınıf", lambda c, ctx: c.name + (f" ({c.short})" if c.short else "")),
            ("Seviye", lambda c, ctx: c.grade or "–"),
            ("Sınıf öğretmeni", lambda c, ctx: c.class_teacher.full_name if c.class_teacher else "–"),
            ("Sınıf dersliği", lambda c, ctx: c.home_classroom or "–"),
            ("Bölünmeler", lambda c, ctx: _divisions_cell(c)),
            ("Haftalık yük", lambda c, ctx: _load_badge(ctx["class_loads"].get(c.id))),
        ],
        availability="school_class", order=("grade", "sort_key", "name"), prefetch=("divisions__groups", "class_teacher"),
        tabs=(
            ("genel", "Genel", (
                ("Kimlik", "Uzun ad çıktılarda, kısa ad ana görünümde kullanılır.", ("name", "short", "grade", "uybs_no")),
                ("Sınıf", "Sınıf öğretmeni, sınıfın dersliği ve öğrenci sayısı.", ("class_teacher", "home_classroom", "student_count")),
            )),
            ("kisitlar", "Kısıtlar", (
                ("Günlük ders sayısı", "Boş bırakılan alan sınır koymaz.", ("min_periods_per_day", "max_periods_per_day")),
            )),
        ),
        sort=lambda c: (c.grade or 0, natural_key(c.name)),
        nav_sub=lambda c, ctx: " · ".join(filter(None, [c.short if c.short != c.name else "", _hours((ctx["class_loads"].get(c.id) or (0, 0))[0])])),
    ),
    "derslikler": Entity(
        "derslikler", Classroom, forms.ClassroomForm, "Derslikler", "Derslik",
        [("Ad", lambda r, ctx: r.name), ("Kısa ad", lambda r, ctx: r.short), ("Kapasite", lambda r, ctx: r.capacity or "–"), ("Aynı anda", lambda r, ctx: r.max_lessons if r.max_lessons > 1 else "–"), ("Bina", lambda r, ctx: r.building or "–")],
        availability="classroom", order=("name",),
        tabs=(("genel", "Genel", (
            ("Derslik", "Kapasite, öğrenci sayısı kontrolü için; “aynı anda” birden çok dersin aynı derslikte olabileceği sayıdır.", ("name", "short", "capacity", "max_lessons", "building")),
        )),),
        nav_sub=lambda r, ctx: " · ".join(filter(None, [r.short if r.short != r.name else "", f"{r.capacity} kişi" if r.capacity else ""])),
    ),
    "binalar": Entity(
        "binalar", Building, forms.BuildingForm, "Binalar", "Bina",
        [("Ad", lambda b, ctx: b.name)], order=("name",),
    ),
    "kart-iliskileri": Entity(
        "kart-iliskileri", CardRelationship, forms.RelationshipForm, "Kart ilişkileri", "Kart ilişkisi",
        [
            ("Ad", lambda r, ctx: r.name),
            ("Koşul", lambda r, ctx: r.get_condition_display()
                + (f" · N={r.param}" if r.condition in r.USES_N else "")
                + (f" (istisna {r.param_max})" if r.param_max and r.condition in r.SOFT_TARGET else "")
                + (f" · {len(r.time_map)} saat işaretli" if r.condition in r.USES_MAP and r.time_map else "")),
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


def _entity_ctx(school, entity):
    ctx = {}
    if entity.model in (Teacher, SchoolClass):
        ctx["teacher_loads"], ctx["class_loads"] = loads(school)
    return ctx


def _sorted(entity, objs):
    """Doğal sıralama (1, 2, … 10; Türkçe harf sırası)."""
    return sorted(objs, key=entity.sort or (lambda o: natural_key(str(o))))


def _navigator(school, entity, current, ctx):
    """Düzenleme ekranının solundaki kayıt listesi ve önceki/sonraki kayıt."""
    objs = _sorted(entity, entity.model.objects.filter(school=school))
    items = [{
        "id": o.pk,
        "label": entity.nav_label(o, ctx) if entity.nav_label else str(o),
        "sub": entity.nav_sub(o, ctx) if entity.nav_sub else "",
        "url": reverse("timetable:data_edit", args=[school.pk, entity.slug, o.pk]),
        "active": current is not None and o.pk == current.pk,
    } for o in objs]
    index = next((i for i, item in enumerate(items) if item["active"]), None)
    return {
        "items": items,
        "prev": items[index - 1]["url"] if index else "",
        "next": items[index + 1]["url"] if index is not None and index + 1 < len(items) else "",
        "position": f"{index + 1} / {len(items)}" if index is not None else "",
    }


def _tabs(tab_specs, form, extra=()):
    """Sekme → bölüm → alan yapısı; tanımsız alanlar ilk bölüme eklenir. extra: alansız sekmeler."""
    names = list(form.fields)
    used = {f for _, _, sections in tab_specs for _, _, fields in sections for f in fields}
    tabs = []
    for key, title, sections in tab_specs or (("genel", "Genel", (("", "", ()),)),):
        tab = {"key": key, "title": title, "sections": [], "errors": False}
        for heading, help_text, fields in sections:
            bound = [form[f] for f in fields if f in form.fields]
            tab["sections"].append({"title": heading, "help": help_text, "fields": bound})
            tab["errors"] |= any(b.errors for b in bound)
        tabs.append(tab)
    rest = [form[f] for f in names if f not in used]
    if rest:
        tabs[0]["sections"][0]["fields"] = list(tabs[0]["sections"][0]["fields"]) + rest
        tabs[0]["errors"] |= any(b.errors for b in rest)
    for key, title in extra:
        tabs.append({"key": key, "title": title, "sections": None, "errors": False})
    return tabs


def _wants_json(request):
    return request.headers.get("X-Requested-With") == "fetch"


def _form_errors(form):
    return JsonResponse({
        "ok": False,
        "message": "Kaydedilemedi: işaretli alanları düzeltin.",
        "errors": {name: [str(e) for e in errs] for name, errs in form.errors.items() if name != "__all__"},
        "non_field": [str(e) for e in form.non_field_errors()],
    }, status=400)


def entity_list(request, pk, slug):
    school, entity = _school(pk), _entity(slug)
    qs = entity.model.objects.filter(school=school).order_by(*entity.order).prefetch_related(*entity.prefetch)
    if entity.model is Subject:
        qs = qs.annotate(n_lessons=Count("lesson"))
    ctx = _entity_ctx(school, entity)
    rows = [{"obj": obj, "cells": [fn(obj, ctx) for _, fn in entity.columns]} for obj in _sorted(entity, qs)]
    return render(
        request,
        "timetable/data/list.html",
        _nav(school, "data", data_nav=slug, entity=entity, headers=[h for h, _ in entity.columns], rows=rows),
    )


def _availability_qs(school, field, obj):
    """field == "school": hedefsiz (okul geneli) kayıtlar."""
    if field == "school":
        return Availability.objects.filter(school=school, **{f"{f}__isnull": True for f in Availability.TARGET_FIELDS})
    return Availability.objects.filter(**{field: obj})


def _availability_grid(school, field, obj):
    states = {}
    if obj is not None:
        for a in _availability_qs(school, field, obj):
            states[f"{a.day}-{a.period}"] = a.state
    return {
        "days": school.day_names,
        "periods": [{"name": p.name, "start": p.start_time.strftime("%H:%M") if p.start_time else ""} for p in school.periods.all()],
        "states": states,
    }


def _save_availability(school, field, obj, raw):
    if raw is None:  # formda ızgara yoksa mevcut kayıtlar korunur
        return
    try:
        states = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return
    _availability_qs(school, field, obj).delete()
    target = {} if field == "school" else {field: obj}
    rows = []
    for key, state in states.items():
        if state not in (Availability.NO, Availability.MAYBE):
            continue
        try:
            day, period = (int(x) for x in key.split("-"))
        except ValueError:
            continue
        if day < school.days_per_week and period < school.periods.count():
            rows.append(Availability(school=school, day=day, period=period, state=state, **target))
    Availability.objects.bulk_create(rows)


# --- müsaitliği birden çok kayda uygulama ---------------------------------------------------------

AVAILABILITY_KINDS = {
    "sinif": ("school_class", SchoolClass, "Sınıflar", "sınıf"),
    "ogretmen": ("teacher", Teacher, "Öğretmenler", "öğretmen"),
    "derslik": ("classroom", Classroom, "Derslikler", "derslik"),
    "ders-adi": ("subject", Subject, "Ders adları", "ders adı"),
}
MODES = {
    "replace": "Aynısı olsun (seçilenlerin müsaitliği bu ızgarayla değişir)",
    "close": "İşaretlileri ekle (yalnızca işaretli hücreler kapanır/koşullu olur, diğerleri korunur)",
    "open": "İşaretlileri aç (işaretli hücrelerdeki kapatmalar kaldırılır)",
}


def _parse_states(school, raw):
    try:
        states = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    out, periods = {}, school.periods.count()
    for key, state in states.items():
        try:
            day, period = (int(x) for x in key.split("-"))
        except ValueError:
            continue
        if state in (Availability.NO, Availability.MAYBE) and day < school.days_per_week and period < periods:
            out[(day, period)] = state
    return out


def apply_availability(school, field, objs, states, mode="replace"):
    """Aynı ızgarayı birden çok kayda uygular. Dönüş: değişen kayıt sayısı."""
    for obj in objs:
        qs = Availability.objects.filter(**{field: obj})
        if mode == "replace":
            qs.delete()
        elif states:
            qs.filter(_cells_q(states)).delete()
        if mode != "open":
            Availability.objects.bulk_create(
                Availability(school=school, day=d, period=p, state=st, **{field: obj}) for (d, p), st in states.items()
            )
    return len(objs)


def _cells_q(states):
    from django.db.models import Q

    q = Q(pk__in=[])
    for d, p in states:
        q |= Q(day=d, period=p)
    return q


def _copy_targets(school, field, obj):
    """Izgara altındaki "diğerlerine de uygula" listesi: aynı türdeki diğer kayıtlar, gruplarıyla."""
    kind = next((k for k, v in AVAILABILITY_KINDS.items() if v[0] == field), None)
    if kind is None:
        return None
    model = AVAILABILITY_KINDS[kind][1]
    items = []
    for o in model.objects.filter(school=school).exclude(pk=getattr(obj, "pk", None)):
        items.append({"id": o.pk, "name": _target_name(o), "group": _target_group(o)})
    return {"kind": kind, "label": AVAILABILITY_KINDS[kind][3], "items": items,
            "groups": sorted({i["group"] for i in items if i["group"]})}


def _target_name(o):
    if isinstance(o, Teacher):
        return o.full_name
    if isinstance(o, SchoolClass):
        return o.short or o.name
    return str(o)


def _target_group(o):
    """Hızlı seçim kümesi: sınıfta kısa adın harf kısmı (1SVN → SVN), derslikte bina, ders adında kod öneki."""
    import re

    if isinstance(o, SchoolClass):
        m = re.search(r"[^\d\W]+", o.short or "", re.UNICODE)
        return m[0] if m else (str(o.grade) if o.grade else "")
    if isinstance(o, Classroom):
        return str(o.building) if o.building_id else ""
    if isinstance(o, Subject):
        return (o.short or "")[:3]
    return ""


def _apply_copies(request, school, field, raw):
    ids = [int(x) for x in request.POST.getlist("copy_to") if x.isdigit()]
    if not ids:
        return 0
    kind = next(k for k, v in AVAILABILITY_KINDS.items() if v[0] == field)
    objs = list(AVAILABILITY_KINDS[kind][1].objects.filter(school=school, pk__in=ids))
    mode = request.POST.get("copy_mode") if request.POST.get("copy_mode") in MODES else "replace"
    return apply_availability(school, field, objs, _parse_states(school, raw), mode)


def bulk_availability(request, pk):
    """Toplu müsaitlik: seçilen sınıflar/öğretmenler/dersliklerde aynı saatleri birlikte kapat ya da aç."""
    school = _school(pk)
    kind = request.GET.get("tur") or request.POST.get("tur") or "sinif"
    if kind not in AVAILABILITY_KINDS:
        kind = "sinif"
    field, model, title, singular = AVAILABILITY_KINDS[kind]
    if request.method == "POST":
        ids = [int(x) for x in request.POST.getlist("copy_to") if x.isdigit()]
        objs = list(model.objects.filter(school=school, pk__in=ids))
        mode = request.POST.get("copy_mode") if request.POST.get("copy_mode") in MODES else "close"
        states = _parse_states(school, request.POST.get("availability"))
        if not objs:
            messages.error(request, f"Önce en az bir {singular} seçin.")
        elif mode != "replace" and not states:
            messages.error(request, "Izgarada en az bir hücre işaretleyin.")
        else:
            with transaction.atomic():
                n = apply_availability(school, field, objs, states, mode)
            verb = {"replace": "müsaitliği değiştirildi", "close": "işaretli saatleri kapatıldı", "open": "işaretli saatleri açıldı"}[mode]
            messages.success(request, f"{n} {singular} için {verb}.")
        return redirect(f"{reverse('timetable:bulk_availability', args=[school.pk])}?tur={kind}")
    source = None
    source_id = request.GET.get("kaynak")
    if source_id and source_id.isdigit():
        source = model.objects.filter(school=school, pk=source_id).first()
    grid = _availability_grid(school, field, source)
    targets = _copy_targets(school, field, None)
    return render(request, "timetable/data/bulk_availability.html", _nav(
        school, "data", data_nav="toplu-musaitlik", kind=kind, kinds={k: v[2] for k, v in AVAILABILITY_KINDS.items()},
        availability=grid, targets=targets, source=source, modes=MODES, singular=singular,
        sources=targets["items"],
    ))


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
        created = obj is None
        with transaction.atomic():
            obj = form.save()
            copied = 0
            if entity.availability:
                _save_availability(school, entity.availability, obj, request.POST.get("availability"))
                copied = _apply_copies(request, school, entity.availability, request.POST.get("availability"))
            new_divisions = False
            if entity.model is SchoolClass:
                new_divisions = _has_new_divisions(request.POST.get("divisions"))
                _save_divisions(obj, request.POST.get("divisions"))
        message = f"{entity.singular} kaydedildi: {obj}" + (f" · müsaitlik {copied} kayda daha uygulandı." if copied else "")
        url = reverse("timetable:data_edit", args=[school.pk, slug, obj.pk])
        new_url = reverse("timetable:data_new", args=[school.pk, slug])
        if _wants_json(request):
            # Sayfadan çıkmadan kaydet. Yeni kayıt ya da yeni bölünme (kimlik aldı) varsa sayfa kendi adresine yenilenir.
            if created or new_divisions:
                messages.success(request, message)
            ctx = _entity_ctx(school, entity)
            return JsonResponse({
                "ok": True, "message": message, "url": url, "reload": created or new_divisions,
                "next": new_url if request.POST.get("next") == "new" else "",
                "title": entity.nav_label(obj, ctx) if entity.nav_label else str(obj),
                "sub": entity.nav_sub(obj, ctx) if entity.nav_sub else "",
            })
        messages.success(request, message)
        return redirect(new_url if request.POST.get("next") == "new" else url)
    if request.method == "POST" and _wants_json(request):
        return _form_errors(form)

    impact = ""
    if obj is not None:
        impact = _delete_impact(obj)
    ctx = _entity_ctx(school, entity)
    extra = []
    if entity.model is SchoolClass:
        extra.append(("bolunmeler", "Bölünmeler"))
    if entity.availability:
        extra.append(("musaitlik", "Müsaitlik"))
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
            availability=_availability_grid(school, entity.availability, obj) if entity.availability else None,
            copy_targets=_copy_targets(school, entity.availability, obj) if entity.availability else None,
            copy_modes=MODES,
            divisions=_division_rows(obj) if entity.model is SchoolClass else None,
            other_classes=school.classes.exclude(pk=obj.pk) if obj is not None and entity.model is SchoolClass else None,
            tabs=_tabs(entity.tabs, form, extra),
            form_id="entity-form",
            navigator=_navigator(school, entity, obj, ctx),
            record_sub=(entity.nav_sub(obj, ctx) if entity.nav_sub and obj is not None else ""),
            list_url=reverse("timetable:data_list", args=[school.pk, slug]),
            new_url=reverse("timetable:data_new", args=[school.pk, slug]),
        ),
    )


def _has_new_divisions(raw):
    try:
        rows = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return False
    return any(not row.get("id") or any(not g.get("id") for g in row.get("groups", [])) for row in rows if isinstance(row, dict))


@require_POST
def copy_divisions(request, pk, class_id):
    """Sınıfın bölünme ve gruplarını seçilen sınıflara kopyalar (aSc 9.9). Hedefin bölünmeleri değişir."""
    school = _school(pk)
    source = get_object_or_404(SchoolClass, pk=class_id, school=school)
    targets = SchoolClass.objects.filter(school=school, pk__in=request.POST.getlist("targets")).exclude(pk=source.pk)
    rows = _division_rows(source)
    with transaction.atomic():
        for target in targets:
            existing = {d.name: d for d in target.divisions.prefetch_related("groups")}
            for row in rows:
                division = existing.pop(row["name"], None) or Division.objects.create(school_class=target, name=row["name"])
                names = [g["name"] for g in row["groups"]]
                division.groups.exclude(name__in=names).delete()
                have = set(division.groups.values_list("name", flat=True))
                Group.objects.bulk_create([Group(division=division, name=n) for n in names if n not in have])
            for division in existing.values():
                division.delete()
    if targets:
        messages.success(request, f"Bölünmeler {len(targets)} sınıfa kopyalandı: {', '.join(t.name for t in targets)}.")
    else:
        messages.error(request, "Hedef sınıf seçilmedi.")
    return redirect("timetable:data_edit", pk=school.pk, slug="siniflar", obj_id=source.pk)


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


def _day_time_grid(school):
    """Ayarlar ekranı: kayıtlı her ders saati için günlere göre saat kutuları (boş = varsayılan)."""
    days = school.day_names
    rows = []
    for p in school.periods.all():
        times = p.day_times or {}
        rows.append({
            "pk": p.pk, "index": p.index + 1,
            "default": [f"{p.start_time:%H:%M}" if p.start_time else "", f"{p.end_time:%H:%M}" if p.end_time else ""],
            "cells": [{"day": d, "start": (times.get(str(d)) or ["", ""])[0], "end": (times.get(str(d)) or ["", ""])[1]} for d in range(len(days))],
        })
    return {"days": days, "rows": rows}


def _parse_day_times(school, post):
    """Formdaki gün saatleri → {dönem pk: {gün: [başlangıç, bitiş]}}, hatalar {alan adı: [ileti]}.
    Varsayılanla aynı ya da iki kutusu boş gün kaydedilmez."""
    result, errors = {}, {}
    days = school.day_names
    for p in school.periods.all():
        times = {}
        for d in range(len(days)):
            names = (f"gs-{p.pk}-{d}-start", f"gs-{p.pk}-{d}-end")
            raw = [(post.get(n) or "").strip() for n in names]
            if not any(raw):
                continue
            label = f"{days[d]} {p.index + 1}. saat"
            try:
                start, end = (datetime.time.fromisoformat(x) for x in raw)
            except ValueError:
                errors[names[0] if not raw[0] or ":" not in raw[0] else names[1]] = [f"{label}: başlangıç ve bitişi 08:20 biçiminde yazın."]
                continue
            if end <= start:
                errors[names[1]] = [f"{label}: bitiş başlangıçtan sonra olmalı."]
                continue
            if (start, end) != (p.start_time, p.end_time):
                times[str(d)] = [f"{start:%H:%M}", f"{end:%H:%M}"]
        result[p.pk] = times
    return result, errors


def _school_sub(school):
    return f"{school.days_per_week} gün × {school.periods.count()} ders saati"


def room_wizard(request, pk):
    """Derslik atama sihirbazı (rooms_wizard.py)."""
    from . import rooms_wizard

    school = _school(pk)
    if request.method == "POST":
        before = len(rooms_wizard.roomless(school))
        n_classes, n_subjects = rooms_wizard.apply(school, request.POST)
        after = len(rooms_wizard.roomless(school))
        messages.success(request, f"{n_classes} sınıfa derslik, {n_subjects} ders adına varsayılan derslik atandı. "
                                  f"Dersliği belirsiz ders: {before} → {after}.")
        return redirect("timetable:room_wizard", pk=school.pk)
    return render(request, "timetable/data/room_wizard.html", _nav(
        school, "data", data_nav="derslik-atama", data=rooms_wizard.analyze(school)))


def school_settings(request, pk):
    school = _school(pk)
    form = forms.SchoolForm(request.POST or None, instance=school)
    formset = forms.PeriodFormSet(request.POST or None, queryset=school.periods.all(), prefix="periods")
    ajax = _wants_json(request)
    day_times, day_errors = _parse_day_times(school, request.POST) if request.method == "POST" else ({}, {})
    if request.method == "POST" and day_errors:
        if ajax:
            return JsonResponse({"ok": False, "message": "Günlere göre saatlerde hata var.", "errors": day_errors,
                                 "non_field": [m for msgs in day_errors.values() for m in msgs]}, status=400)
        for msgs in day_errors.values():
            messages.error(request, msgs[0])
    if request.method == "POST" and not day_errors and form.is_valid() and formset.is_valid():
        kept = [f for f in formset.forms if f.has_changed() or f.instance.pk]
        kept = [f for f in kept if not (formset.can_delete and formset._should_delete_form(f))]
        structure_changed = bool(formset.deleted_forms) or any(not f.instance.pk for f in kept)
        if not kept:
            if ajax:
                return JsonResponse({"ok": False, "message": "En az bir ders saati olmalı.", "errors": {}, "non_field": ["En az bir ders saati olmalı."]}, status=400)
            messages.error(request, "En az bir ders saati olmalı.")
        else:
            with transaction.atomic():
                form.save()
                _save_availability(school, "school", school, request.POST.get("availability"))
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
                    if period.pk in day_times:
                        period.day_times = day_times[period.pk]
                    period.save()
            message = "Program ayarları ve ders saatleri kaydedildi."
            if ajax:
                # Saat eklendi/silindiyse satırlar yeni kimlik ve sırayla yeniden açılmalı.
                if structure_changed:
                    messages.success(request, message)
                return JsonResponse({"ok": True, "message": message, "reload": structure_changed,
                                     "url": reverse("timetable:school_settings", args=[school.pk]),
                                     "title": school.name, "sub": _school_sub(school)})
            messages.success(request, message)
            return redirect("timetable:school_settings", pk=school.pk)
    if request.method == "POST" and ajax:
        errors = {name: [str(e) for e in errs] for name, errs in form.errors.items() if name != "__all__"}
        non_field = [str(e) for e in form.non_field_errors()] + [str(e) for e in formset.non_form_errors()]
        for f in formset.forms:
            for name, errs in f.errors.items():
                if name == "__all__":
                    row = int(f.prefix.split("-")[-1]) + 1 if f.prefix and f.prefix.split("-")[-1].isdigit() else ""
                    non_field += [f"{row}. saat: {e}" for e in errs]
                else:
                    errors[f.add_prefix(name)] = [str(e) for e in errs]
        return JsonResponse({"ok": False, "message": "Kaydedilemedi: işaretli alanları düzeltin.", "errors": errors, "non_field": non_field}, status=400)
    tab_specs = (("program", "Program", (
        ("Program", "Programın adı, haftalık gün sayısı ve hafta/dönem döngüsü.", ("name", "days_per_week", "weeks_count", "terms_count")),
        ("Birlikte çalışan programlar", "Bu programların yayındaki programında dolu olan öğretmen ve derslik saatleri burada kapalı sayılır.", ("linked_programs",)),
    )),)
    return render(
        request,
        "timetable/data/settings_editor.html",
        _nav(
            school, "data", data_nav="okul", form=form, formset=formset, creating=False, form_id="settings-form",
            tabs=_tabs(tab_specs, form, (("saatler", "Ders saatleri"), ("kapali", "Kapalı saatler"))),
            record_sub=_school_sub(school), navigator={}, day_grid=_day_time_grid(school),
            availability=_availability_grid(school, "school", school),
            availability_title="Okul geneli kapalı saatler",
            availability_help="Burada kapatılan saatlere hiçbir ders konmaz (ör. Cuma 6. saatten sonra ders yok, "
            "toplantı günü son saat boş). Koşullu (?) saatlere mümkünse ders konmaz.",
        ),
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


BULK_MODES = {"replace": "yerine koy", "add": "ekle", "remove": "çıkar"}


def lessons(request, pk):
    """Dersler: sınıfa göre gruplu ve katlanır liste (satırları tarayıcı çizer), arama/süzgeç ve
    seçili derslerde toplu düzenleme (öğretmen, derslik, haftalık saat, kart uzunluğu, günde en fazla, sil)."""
    school = _school(pk)
    if request.method == "POST":
        message, level = _lesson_bulk(school, request.POST)
        getattr(messages, level)(request, message)
        return redirect(reverse("timetable:lessons", args=[school.pk]) + ("?" + request.POST.get("query", "") if request.POST.get("query") else ""))
    # İlişkiler ara tablolardan kimlik olarak okunur (binlerce dersin her biri için nesne kurmadan).
    qs = Lesson.objects.filter(school=school).select_related("subject").only(
        "id", "periods_per_week", "card_length", "split", "max_per_day", "subject__name", "subject__short", "subject__color")
    links = defaultdict(lambda: defaultdict(list))
    for name, model_field in (("classes", "schoolclass_id"), ("teachers", "teacher_id"), ("classrooms", "classroom_id"), ("groups", "group_id")):
        through = getattr(Lesson, name).through
        for lesson_id, target in through.objects.filter(lesson__school=school).values_list("lesson_id", model_field):
            links[name][lesson_id].append(target)
    class_names = {c.pk: c.short or c.name for c in school.classes.all()}
    teacher_names = {t.pk: _teacher_name(t) for t in school.teachers.all()}
    room_names_ = {r.pk: str(r) for r in school.classrooms.all()}
    group_names = dict(Group.objects.filter(division__school_class__school=school).values_list("pk", "name"))
    teacher_loads, class_loads = loads(school)
    cells = school.days_per_week * school.periods.count()
    rows, by_class, loose = [], defaultdict(list), []
    for lesson in sorted(qs, key=lambda x: (natural_key(x.subject.name), x.pk)):
        lengths = lesson.card_lengths()
        classes = links["classes"].get(lesson.pk, [])
        teachers = links["teachers"].get(lesson.pk, [])
        rows.append({
            "id": lesson.pk, "s": lesson.subject.name, "k": lesson.subject.short or "", "c": lesson.subject.color,
            "cl": ", ".join(class_names[c] for c in classes if c in class_names), "ci": classes,
            "g": ", ".join(sorted({group_names.get(g, "") for g in links["groups"].get(lesson.pk, [])})),
            "t": ", ".join(teacher_names[t] for t in teachers if t in teacher_names), "ti": teachers,
            "r": ", ".join(room_names_[r] for r in links["classrooms"].get(lesson.pk, []) if r in room_names_),
            "h": lesson.periods_per_week, "p": "+".join(map(str, lengths)) if len(lengths) > 1 and lesson.card_length > 1 else "",
            "m": lesson.max_per_day or "",
        })
        for c in classes:
            by_class[c].append(lesson.pk)
        if not classes:
            loose.append(lesson.pk)
    groups = [{
        "id": c.pk, "name": c.name, "short": c.short if c.short != c.name else "",
        "hours": class_loads.get(c.pk, (0, cells))[0], "cap": class_loads.get(c.pk, (0, cells))[1],
        "lessons": by_class.get(c.pk, []),
        "table": reverse("timetable:class_lessons", args=[school.pk, c.pk]),
        "new": reverse("timetable:lesson_new", args=[school.pk]) + f"?sinif={c.pk}",
    } for c in _sorted(ENTITIES["siniflar"], school.classes.all())]
    if loose:
        groups.append({"id": 0, "name": "Sınıfsız dersler", "short": "toplantı, hazırlık", "hours": sum(r["h"] for r in rows if not r["ci"]),
                       "cap": 0, "lessons": loose, "table": "", "new": reverse("timetable:lesson_new", args=[school.pk])})
    teachers = _sorted(ENTITIES["ogretmenler"], school.teachers.all())
    return render(
        request,
        "timetable/data/lessons.html",
        _nav(
            school, "data", data_nav="dersler",
            payload={"rows": rows, "groups": groups, "edit": reverse("timetable:lesson_edit", args=[school.pk, 0])},
            count=len(rows), total=sum(r["h"] for r in rows),
            teachers=teachers, rooms=_sorted(ENTITIES["derslikler"], school.classrooms.all()),
            classes=[g for g in groups if g["id"]], modes=BULK_MODES,
            filters={"sinif": request.GET.get("sinif", ""), "ogretmen": request.GET.get("ogretmen", ""), "q": request.GET.get("q", "")},
        ),
    )


def _lesson_bulk(school, post):
    """Seçili derslere toplu değişiklik. Dönüş: (ileti, messages düzeyi)."""
    ids = [int(x) for x in post.getlist("ders") if x.isdigit()]
    lessons = list(Lesson.objects.filter(school=school, pk__in=ids))
    if not lessons:
        return "Önce ders seçin.", "error"
    action, mode = post.get("islem"), post.get("mod") if post.get("mod") in BULK_MODES else "replace"
    n = len(lessons)
    with transaction.atomic():
        if action in ("ogretmen", "derslik"):
            model, attr = (Teacher, "teachers") if action == "ogretmen" else (Classroom, "classrooms")
            chosen = list(model.objects.filter(school=school, pk__in=[int(x) for x in post.getlist("deger") if x.isdigit()]))
            if not chosen and mode != "replace":
                return "Eklenecek ya da çıkarılacak kaydı seçin.", "error"
            for lesson in lessons:
                getattr(lesson, attr).set(chosen) if mode == "replace" else (
                    getattr(lesson, attr).add(*chosen) if mode == "add" else getattr(lesson, attr).remove(*chosen))
            what = ", ".join(str(c) if action == "derslik" else _teacher_name(c) for c in chosen) or "boş"
            return f"{n} derste {'öğretmen' if action == 'ogretmen' else 'derslik'} {BULK_MODES[mode]}: {what}.", "success"
        if action in ("saat", "uzunluk", "gunde"):
            raw = (post.get("sayi") or "").strip()
            if action == "gunde" and raw == "":
                value = None
            elif raw.isdigit() and 1 <= int(raw) <= (40 if action == "saat" else 8):
                value = int(raw)
            else:
                return "Geçerli bir sayı girin.", "error"
            field = {"saat": "periods_per_week", "uzunluk": "card_length", "gunde": "max_per_day"}[action]
            for lesson in lessons:
                setattr(lesson, field, value)
                if action in ("saat", "uzunluk"):
                    lesson.split = ""  # dağılım eski saate göreydi
            Lesson.objects.bulk_update(lessons, [field, "split"] if action in ("saat", "uzunluk") else [field])
            from .problem_cache import invalidate

            invalidate()  # bulk_update sinyal göndermez
            label = {"saat": "haftalık saat", "uzunluk": "kart uzunluğu", "gunde": "günde en fazla kart"}[action]
            return f"{n} derste {label}: {value if value is not None else 'sınırsız'}.", "success"
        if action == "sil":
            for lesson in lessons:
                lesson.delete()
            return f"{n} ders silindi (programlardaki kartlarıyla).", "success"
    return "Bilinmeyen işlem.", "error"


def lesson_edit(request, pk, lesson_id=None):
    school = _school(pk)
    lesson = get_object_or_404(Lesson, pk=lesson_id, school=school) if lesson_id else None
    initial = {}
    if lesson is None and request.GET.get("sinif"):
        initial["classes"] = [request.GET["sinif"]]
    form = forms.LessonForm(request.POST or None, instance=lesson, school=school, initial=initial)
    if request.method == "POST" and form.is_valid():
        created = lesson is None
        with transaction.atomic():
            lesson = form.save()
            _save_availability(school, "lesson", lesson, request.POST.get("availability"))
        message = f"Ders kaydedildi: {lesson}"
        url = reverse("timetable:lesson_edit", args=[school.pk, lesson.pk])
        back = request.POST.get("back") or ""
        if back.startswith("/"):
            url += "?" + urlencode({"back": back})
        new_url = reverse("timetable:lesson_new", args=[school.pk]) + "?" + "&".join(f"sinif={c.pk}" for c in lesson.classes.all()[:1])
        if _wants_json(request):
            if created:
                messages.success(request, message)
            return JsonResponse({
                "ok": True, "message": message, "url": url, "reload": created,
                "next": new_url if request.POST.get("next") == "new" else "",
                "title": lesson.subject.name, "sub": _lesson_sub(lesson),
            })
        messages.success(request, message)
        return redirect(new_url if request.POST.get("next") == "new" else url)
    if request.method == "POST" and _wants_json(request):
        return _form_errors(form)
    class_id = (lesson.classes.values_list("pk", flat=True).first() if lesson else None) or request.GET.get("sinif")
    return render(
        request,
        "timetable/data/lesson_form.html",
        _nav(
            school,
            "data",
            data_nav="dersler",
            form=form,
            lesson=lesson,
            back=request.GET.get("back", ""),
            availability=_availability_grid(school, "lesson", lesson),
            availability_help="Bu ders yalnızca bu dersin kartları için geçerlidir; öğretmen ve sınıf müsaitliğiyle birlikte uygulanır.",
            tabs=[{"key": "ders", "title": "Ders", "errors": any(form[f].errors for f in form.fields)},
                  {"key": "musaitlik", "title": "Müsaitlik", "errors": False}],
            navigator=_lesson_navigator(school, lesson, class_id, back=request.GET.get("back", "")),
            form_id="lesson-form",
            record_sub=_lesson_sub(lesson) if lesson else "",
            list_url=request.GET.get("back") if request.GET.get("back", "").startswith("/") else reverse("timetable:lessons", args=[school.pk]),
            new_url=reverse("timetable:lesson_new", args=[school.pk]) + (f"?sinif={class_id}" if class_id else ""),
        ),
    )


def _lesson_sub(lesson):
    teachers = ", ".join(_teacher_name(t) for t in lesson.teachers.all())
    classes = ", ".join(c.short or c.name for c in lesson.classes.all())
    return " · ".join(filter(None, [classes, teachers, f"{lesson.periods_per_week} saat"]))


def _lesson_navigator(school, current, class_id, back=""):
    """Ders düzenlemede soldaki liste: aynı sınıfın dersleri (sınıf yoksa aynı öğretmenin)."""
    qs = Lesson.objects.filter(school=school).select_related("subject").prefetch_related("classes", "teachers")
    title = "Dersler"
    cls = SchoolClass.objects.filter(school=school, pk=class_id).first() if str(class_id or "").isdigit() else None
    if cls is not None:
        qs, title = qs.filter(classes=cls), f"{cls.short or cls.name} dersleri"
    elif current is not None and current.teachers.exists():
        teacher = current.teachers.first()
        qs, title = qs.filter(teachers=teacher), f"{_teacher_name(teacher)} dersleri"
    else:
        qs = qs.none()
    suffix = "?" + urlencode({"back": back}) if back.startswith("/") else ""
    lessons = sorted(qs.distinct(), key=lambda x: (natural_key(x.subject.name), x.pk))
    items = [{
        "id": x.pk, "label": x.subject.name, "sub": _lesson_sub(x),
        "url": reverse("timetable:lesson_edit", args=[school.pk, x.pk]) + suffix,
        "active": current is not None and x.pk == current.pk,
    } for x in lessons]
    index = next((i for i, item in enumerate(items) if item["active"]), None)
    return {
        "title": title, "items": items,
        "prev": items[index - 1]["url"] if index else "",
        "next": items[index + 1]["url"] if index is not None and index + 1 < len(items) else "",
        "position": f"{index + 1} / {len(items)}" if index is not None else "",
    }


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


# --- Excel aktarımı ----------------------------------------------------------------------------


def excel_import(request, pk):
    school = _school(pk)
    result = errors = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            errors = ["Dosya seçilmedi."]
        elif upload.size > 10 * 1024 * 1024:
            errors = ["Dosya çok büyük (en fazla 10 MB)."]
        else:
            try:
                result = importer.import_workbook(school, upload.read(), delete_missing_lessons=request.POST.get("delete_missing") == "on")
            except importer.ImportFailed as exc:
                errors = exc.errors
        if result is not None:
            summary = ", ".join(
                f"{title}: " + ", ".join(f"{n} {label}" for label, n in counts.items() if n) for title, counts in result.items()
            )
            messages.success(request, "Excel aktarıldı. " + (summary or "Değişiklik yok."))
            return redirect("timetable:excel_import", pk=school.pk)
    return render(
        request,
        "timetable/data/excel.html",
        _nav(school, "data", data_nav="excel", errors=errors, sheets=importer.SHEETS, notes=importer.NOTES),
    )


def excel_export(request, pk):
    school = _school(pk)
    response = HttpResponse(
        importer.export_workbook(school), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="okul-verisi-{school.pk}.xlsx"'
    return response


# --- ders dağıtım çizelgesi (toplu öğretmen/ders ataması) ---------------------------------------


def _simple_lessons(school):
    """(ders adı, sınıf) → basit ders; basit olmayanlar (gruplu/birleşik/çok öğretmenli) ayrı sayılır."""
    simple, complex_hours = {}, defaultdict(int)
    lessons = Lesson.objects.filter(school=school).prefetch_related("classes", "groups", "teachers", "classrooms")
    for lesson in lessons:
        classes = list(lesson.classes.all())
        if len(classes) == 1 and not lesson.groups.all() and len(lesson.teachers.all()) <= 1 and len(lesson.classrooms.all()) <= 1:
            key = (lesson.subject_id, classes[0].id)
            if key not in simple:
                simple[key] = lesson
                continue
        for cls in classes:
            complex_hours[(lesson.subject_id, cls.id)] += lesson.periods_per_week
    return simple, complex_hours


def _teacher_loads_all(school):
    loads_ = defaultdict(int)
    for lesson in Lesson.objects.filter(school=school).prefetch_related("teachers"):
        for teacher in lesson.teachers.all():
            loads_[teacher.id] += lesson.periods_per_week
    return loads_


def distribution(request, pk):
    school = _school(pk)
    simple, complex_hours = _simple_lessons(school)
    loads_all = _teacher_loads_all(school)
    simple_by_teacher = defaultdict(int)
    for lesson in simple.values():
        for teacher in lesson.teachers.all():
            simple_by_teacher[teacher.id] += lesson.periods_per_week
    classes = list(school.classes.all())
    data = {
        "subjects": [{"id": s.id, "name": s.name, "short": s.short or s.name[:4], "color": s.color} for s in school.subjects.order_by("name")],
        "classes": [{"id": c.id, "name": c.name, "grade": c.grade} for c in classes],
        "teachers": [
            {
                "id": t.id,
                "name": t.full_name,
                "short": t.short or t.full_name,
                # Matris dışındaki (gruplu/birleşik) derslerden gelen sabit yük:
                "fixed": loads_all.get(t.id, 0) - simple_by_teacher.get(t.id, 0),
                "target": t.target_periods,
                "subjects": [s.id for s in t.subjects.all()],
            }
            for t in school.teachers.prefetch_related("subjects")
        ],
        "cells": {
            f"{subject_id}-{class_id}": {
                "hours": lesson.periods_per_week,
                "length": lesson.card_length,
                "teacher": next((t.id for t in lesson.teachers.all()), None),
            }
            for (subject_id, class_id), lesson in simple.items()
        },
        "complex": {f"{s}-{c}": h for (s, c), h in complex_hours.items()},
        "capacity": school.days_per_week * school.periods.count(),
        "saveUrl": reverse("timetable:distribution_save", args=[school.pk]),
        "classUrl": reverse("timetable:class_lessons", args=[school.pk, 0]),
    }
    return render(request, "timetable/data/distribution.html", _nav(school, "data", data_nav="dagitim", data=data))


@require_POST
def distribution_save(request, pk):
    school = _school(pk)
    try:
        cells = json.loads(request.body or b"{}").get("cells", [])
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "message": "Geçersiz istek."}, status=400)
    subjects = {s.id: s for s in school.subjects.all()}
    classes = {c.id: c for c in school.classes.all()}
    teachers = {t.id: t for t in school.teachers.all()}
    simple, _ = _simple_lessons(school)
    counts = defaultdict(int)
    with transaction.atomic():
        for cell in cells:
            subject = subjects.get(cell.get("subject"))
            cls = classes.get(cell.get("class"))
            if subject is None or cls is None:
                continue
            try:
                hours = max(0, int(cell.get("hours") or 0))
                length = min(4, max(1, int(cell.get("length") or 1)))
            except (TypeError, ValueError):
                continue
            teacher = teachers.get(cell.get("teacher"))
            lesson = simple.get((subject.id, cls.id))
            if hours == 0:
                if lesson is not None:
                    lesson.delete()
                    counts["silinen"] += 1
                continue
            if lesson is None:
                lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=hours, card_length=length)
                lesson.classes.set([cls])
                counts["eklenen"] += 1
            else:
                lesson.periods_per_week, lesson.card_length = hours, length
                lesson.save(update_fields=["periods_per_week", "card_length"])
                counts["güncellenen"] += 1
            lesson.teachers.set([teacher] if teacher else [])
    summary = ", ".join(f"{n} {label}" for label, n in counts.items()) or "değişiklik yok"
    return JsonResponse({"ok": True, "message": f"Ders dağıtımı kaydedildi: {summary}.", "counts": counts})


def _split_classes(text, known):
    """"9-A, 9-B" / "9-A 9-B" / "Hazırlık 1" gibi yazımları sınıf adlarına ayırır (known: küçük harfli adlar)."""
    import re

    result = []
    for part in re.split(r"[,;/]+", str(text or "")):
        part = part.strip()
        if not part:
            continue
        if part.casefold() in known:
            result.append(part)
        else:
            result.extend(token for token in part.split() if token)
    return result


@require_POST
def distribution_paste(request, pk):
    """Excel'den yapıştırılan "Öğretmen | Ders | Sınıflar | Saat | Blok" satırlarını önizler ya da uygular."""
    school = _school(pk)
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "message": "Geçersiz istek."}, status=400)
    apply = body.get("apply") is True
    text = str(body.get("text") or "")

    def key(value):
        return str(value or "").strip().casefold()

    teachers = {}
    for t in school.teachers.all():
        teachers[key(t.full_name)] = t
        if t.short:
            teachers.setdefault(key(t.short), t)
    subjects = {}
    for s in school.subjects.all():
        subjects[key(s.name)] = s
        if s.short:
            subjects.setdefault(key(s.short), s)
    classes = {key(c.name): c for c in school.classes.all()}

    rows, new_teachers, new_subjects = [], {}, {}
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = [p.strip() for p in (line.split("\t") if "\t" in line else line.split(";"))]
        parts += [""] * (5 - len(parts))
        teacher_name, subject_name, class_text, hours_text, length_text = parts[:5]
        if number == 1 and key(teacher_name) in ("öğretmen", "ogretmen") and not hours_text.strip().isdigit():
            continue  # başlık satırı
        row = {"line": number, "teacher": teacher_name, "subject": subject_name, "classes": [], "hours": hours_text, "length": length_text or "1", "notes": [], "errors": []}
        if not hours_text.strip().isdigit() or int(hours_text) < 1:
            row["errors"].append("haftalık saat sayı olmalı")
        if length_text.strip() and (not length_text.strip().isdigit() or not 1 <= int(length_text) <= 4):
            row["errors"].append("blok 1–4 arası olmalı")
        if teacher_name and key(teacher_name) not in teachers:
            if len(teacher_name.split()) < 2:
                row["errors"].append(f"“{teacher_name}” öğretmeni yok (yeni öğretmen için ad ve soyad yazın)")
            else:
                new_teachers[key(teacher_name)] = teacher_name
                row["notes"].append("yeni öğretmen")
        if not subject_name:
            row["errors"].append("ders adı boş")
        elif key(subject_name) not in subjects:
            new_subjects[key(subject_name)] = subject_name
            row["notes"].append("yeni ders adı")
        for name in _split_classes(class_text, classes):
            if key(name) in classes:
                row["classes"].append(classes[key(name)].name)
            else:
                row["errors"].append(f"“{name}” sınıfı yok")
        if not class_text.strip():
            row["errors"].append("sınıf boş")
        rows.append(row)

    errors = sum(1 for r in rows if r["errors"])
    if not apply or errors or not rows:
        return JsonResponse({"ok": True, "applied": False, "rows": rows, "errors": errors})

    counts = defaultdict(int)
    with transaction.atomic():
        palette = ["#dfe7fd", "#fde2e4", "#e2ece9", "#fff1e6", "#e9f5db", "#f0efeb", "#cddafd", "#fad2e1"]
        for i, (k, name) in enumerate(new_subjects.items()):
            subjects[k] = Subject.objects.create(school=school, name=name, color=palette[i % len(palette)])
            counts["yeni ders adı"] += 1
        for k, name in new_teachers.items():
            first, _, last = name.rpartition(" ")
            teachers[k] = Teacher.objects.create(school=school, first_name=first, last_name=last)
            counts["yeni öğretmen"] += 1
        simple, _ = _simple_lessons(school)
        for row in rows:
            subject = subjects[key(row["subject"])]
            teacher = teachers.get(key(row["teacher"])) if row["teacher"] else None
            hours, length = int(row["hours"]), int(row["length"] or 1)
            for class_name in row["classes"]:
                cls = classes[key(class_name)]
                lesson = simple.get((subject.id, cls.id))
                if lesson is None:
                    lesson = Lesson.objects.create(school=school, subject=subject, periods_per_week=hours, card_length=length)
                    lesson.classes.set([cls])
                    simple[(subject.id, cls.id)] = lesson
                    counts["yeni ders"] += 1
                else:
                    lesson.periods_per_week, lesson.card_length = hours, length
                    lesson.save(update_fields=["periods_per_week", "card_length"])
                    counts["güncellenen ders"] += 1
                lesson.teachers.set([teacher] if teacher else [])
    summary = ", ".join(f"{n} {label}" for label, n in counts.items())
    messages.success(request, f"Yapıştırılan dağıtım aktarıldı: {summary}.")
    return JsonResponse({"ok": True, "applied": True, "message": summary})
