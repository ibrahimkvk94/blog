from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import Card, School, Timetable
from .services import check_school, generate_timetable, verify_timetable

VIEW_KINDS = {
    "sinif": ("Sınıf", "classes"),
    "ogretmen": ("Öğretmen", "teachers"),
    "derslik": ("Derslik", "classrooms"),
}


def school_list(request):
    return render(request, "timetable/school_list.html", {"schools": School.objects.all()})


def school_detail(request, pk):
    school = get_object_or_404(School, pk=pk)
    return render(
        request,
        "timetable/school_detail.html",
        {
            "school": school,
            "issues": check_school(school),
            "timetables": school.timetables.all(),
            "counts": {
                "Sınıf": school.classes.count(),
                "Öğretmen": school.teachers.count(),
                "Derslik": school.classrooms.count(),
                "Ders": school.lessons.count(),
            },
        },
    )


@require_POST
def generate(request, pk):
    school = get_object_or_404(School, pk=pk)
    base = None
    if request.POST.get("base"):
        base = get_object_or_404(Timetable, pk=request.POST["base"], school=school)
    try:
        time_limit = max(1, min(600, int(request.POST.get("time_limit") or 30)))
    except ValueError:
        time_limit = 30
    name = request.POST.get("name") or "Yeni program"
    timetable = generate_timetable(school, name, time_limit=time_limit, base=base)
    if timetable.status == Timetable.OK:
        messages.success(request, "Program üretildi.")
    else:
        messages.error(request, "Program üretilemedi; rapora bakın.")
    return redirect("timetable:timetable_detail", pk=timetable.pk)


def _card_matches(card, kind, obj_id):
    if kind == "sinif":
        return any(c.id == obj_id for c in card.lesson.classes.all())
    if kind == "ogretmen":
        return any(t.id == obj_id for t in card.lesson.teachers.all())
    return card.classroom_id == obj_id


def timetable_detail(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    kind = request.GET.get("tur", "sinif")
    if kind not in VIEW_KINDS:
        kind = "sinif"
    kind_label, related = VIEW_KINDS[kind]
    objects = list(getattr(school, related).all())
    selected = None
    if objects:
        try:
            selected_id = int(request.GET.get("id", objects[0].id))
        except ValueError:
            selected_id = objects[0].id
        selected = next((o for o in objects if o.id == selected_id), objects[0])

    cards = list(
        timetable.cards.select_related("lesson__subject", "classroom").prefetch_related(
            "lesson__classes", "lesson__teachers", "lesson__groups"
        )
    )
    periods = list(school.periods.all())
    shown = [c for c in cards if selected and _card_matches(c, kind, selected.id)]
    for card in shown:
        card.group_names = sorted({g.name for g in card.lesson.groups.all()})
    rows = [
        {"period": period, "cells": [[c for c in shown if c.covers(d, period.index)] for d in range(school.days_per_week)]}
        for period in periods
    ]
    violations, stats = verify_timetable(timetable) if timetable.status == Timetable.OK else ([], {})
    return render(
        request,
        "timetable/timetable_detail.html",
        {
            "timetable": timetable,
            "school": school,
            "kind": kind,
            "kind_label": kind_label,
            "kinds": VIEW_KINDS,
            "objects": objects,
            "selected": selected,
            "rows": rows,
            "unplaced": [c for c in cards if not c.is_placed],
            "violations": violations,
            "stats": stats,
        },
    )


@require_POST
def toggle_lock(request, pk):
    card = get_object_or_404(Card, pk=pk)
    card.locked = not card.locked
    card.save(update_fields=["locked"])
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("timetable:timetable_detail", pk=card.timetable_id)
