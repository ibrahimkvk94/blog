import datetime
import json

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import asc_xml, editing, excel, jobs, substitutes
from .demo import create_demo_school
from .grid import KINDS, card_payload, grid_data
from .models import Absence, Card, School, Teacher, Timetable
from .services import check_school, refresh_stale, repair_timetable, request_stop, start_generation

KIND_LABELS = {"sinif": "Sınıflar", "ogretmen": "Öğretmenler", "derslik": "Derslikler"}


def _nav(school, nav, **extra):
    latest = school.timetables.exclude(status__in=[Timetable.FAILED, Timetable.RUNNING]).first()
    return {"school": school, "nav": nav, "latest_timetable": latest, **extra}


# --- sayfalar ----------------------------------------------------------------------------------


def school_list(request):
    schools = School.objects.annotate(
        n_classes=Count("classes", distinct=True),
        n_teachers=Count("teachers", distinct=True),
        n_timetables=Count("timetables", distinct=True),
    )
    return render(request, "timetable/school_list.html", {"schools": schools})


@require_POST
def create_demo(request):
    school = create_demo_school()
    messages.success(request, "Örnek okul oluşturuldu.")
    return redirect("timetable:school_detail", pk=school.pk)


@require_POST
def import_asc(request):
    upload = request.FILES.get("file")
    if not upload:
        messages.error(request, "Dosya seçilmedi.")
        return redirect("timetable:school_list")
    if upload.size > 20 * 1024 * 1024:
        messages.error(request, "Dosya çok büyük (en fazla 20 MB).")
        return redirect("timetable:school_list")
    try:
        school, timetable = asc_xml.import_school(upload.read(), name=upload.name.rsplit(".", 1)[0])
    except asc_xml.AscImportError as exc:
        messages.error(request, f"İçe aktarılamadı: {exc}")
        return redirect("timetable:school_list")
    messages.success(request, f"{school} içe aktarıldı.")
    if timetable:
        return redirect("timetable:timetable_detail", pk=timetable.pk)
    return redirect("timetable:school_detail", pk=school.pk)


def school_detail(request, pk):
    school = get_object_or_404(School, pk=pk)
    timetables = [refresh_stale(t) for t in school.timetables.all()]
    issues = check_school(school)
    lessons = list(school.lessons.all())
    data_url = lambda slug: reverse("timetable:data_list", args=[school.pk, slug])  # noqa: E731
    tiles = [
        {"label": "Sınıf", "value": school.classes.count(), "url": data_url("siniflar")},
        {"label": "Öğretmen", "value": school.teachers.count(), "url": data_url("ogretmenler")},
        {"label": "Derslik", "value": school.classrooms.count(), "url": data_url("derslikler")},
        {"label": "Ders", "value": len(lessons), "hint": f"haftada {sum(x.periods_per_week for x in lessons)} saat", "url": reverse("timetable:lessons", args=[school.pk])},
        {"label": "Zaman ızgarası", "value": f"{school.days_per_week} × {school.periods.count()}", "hint": "gün × saat", "url": reverse("timetable:school_settings", args=[school.pk])},
    ]
    return render(
        request,
        "timetable/school_detail.html",
        _nav(
            school,
            "dashboard",
            issues=issues,
            errors=sum(1 for i in issues if i.level == "error"),
            timetables=timetables,
            tiles=tiles,
        ),
    )


@require_POST
def generate(request, pk):
    school = get_object_or_404(School, pk=pk)
    base = None
    if request.POST.get("base"):
        base = get_object_or_404(Timetable, pk=request.POST["base"], school=school)
    try:
        time_limit = max(5, min(1800, int(request.POST.get("time_limit") or 60)))
    except ValueError:
        time_limit = 60
    mode = request.POST.get("mode")
    if mode not in (Timetable.STRICT, Timetable.RELAXED):
        mode = Timetable.STRICT
    name = (request.POST.get("name") or "").strip() or "Yeni program"
    timetable = start_generation(school, name, time_limit=time_limit, mode=mode, base=base)
    return redirect("timetable:timetable_detail", pk=timetable.pk)


@ensure_csrf_cookie
def timetable_detail(request, pk):
    timetable = refresh_stale(get_object_or_404(Timetable.objects.select_related("school"), pk=pk))
    school = timetable.school
    config = {
        "timetable": timetable.pk,
        "running": timetable.is_running,
        "hasGrid": timetable.has_grid,
        "statusUrl": reverse("timetable:api_status", args=[timetable.pk]),
        "gridUrl": reverse("timetable:api_grid", args=[timetable.pk]),
        "repairUrl": reverse("timetable:api_repair", args=[timetable.pk]),
        "optionsUrl": reverse("timetable:api_card_options", args=[0]),
        "moveUrl": reverse("timetable:api_card_move", args=[0]),
        "unplaceUrl": reverse("timetable:api_card_unplace", args=[0]),
        "lockUrl": reverse("timetable:api_card_lock", args=[0]),
    }
    return render(
        request, "timetable/timetable_detail.html", _nav(school, "timetable", timetable=timetable, config=config)
    )


@require_POST
def stop(request, pk):
    timetable = get_object_or_404(Timetable, pk=pk)
    if timetable.is_running:
        request_stop(timetable)
        messages.info(request, "Durdurma istendi; o ana kadarki en iyi program kaydedilecek.")
    return redirect("timetable:timetable_detail", pk=pk)


@require_POST
def publish(request, pk):
    timetable = get_object_or_404(Timetable, pk=pk)
    if not timetable.has_grid:
        messages.error(request, "Yalnızca üretilmiş programlar yayınlanabilir.")
    else:
        School.objects.filter(pk=timetable.school_id).update(active_timetable=timetable)
        messages.success(request, f"“{timetable.name}” yayındaki program olarak ayarlandı.")
    return redirect("timetable:timetable_detail", pk=pk)


def print_view(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    kind = request.GET.get("tur", "sinif")
    if kind not in KINDS:
        kind = "sinif"
    school = timetable.school
    periods = list(school.periods.all())
    cards = [
        card_payload(c, kind)
        for c in timetable.cards.filter(day__isnull=False)
        .select_related("lesson__subject", "classroom")
        .prefetch_related("lesson__classes", "lesson__teachers", "lesson__groups")
    ]
    pages = []
    for obj in getattr(school, KINDS[kind]).all():
        mine = [c for c in cards if obj.id in c["rows"]]
        rows = [
            {
                "period": period,
                "cells": [
                    [c for c in mine if c["day"] == d and c["period"] <= period.index < c["period"] + c["length"]]
                    for d in range(school.days_per_week)
                ],
            }
            for period in periods
        ]
        title = f"{obj.first_name} {obj.last_name}" if kind == "ogretmen" else str(obj)
        pages.append({"title": title, "rows": rows})
    return render(
        request,
        "timetable/print.html",
        {
            "timetable": timetable,
            "school": school,
            "pages": pages,
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "days": school.day_names,
        },
    )


def export_excel(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    response = HttpResponse(
        excel.export(timetable), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="ders-programi-{timetable.pk}.xlsx"'
    return response


def export_asc(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    response = HttpResponse(asc_xml.export_school(timetable.school, timetable), content_type="application/xml")
    response["Content-Disposition"] = f'attachment; filename="asc-{timetable.pk}.xml"'
    return response


def substitutions(request, pk):
    school = get_object_or_404(School, pk=pk)
    try:
        date = datetime.date.fromisoformat(request.GET.get("tarih") or request.POST.get("tarih") or "")
    except ValueError:
        date = timezone.localdate()
    timetable = school.active_timetable or school.timetables.filter(status=Timetable.OK).first()

    if request.method == "POST" and timetable is not None:
        action = request.POST.get("action")
        if action == "add":
            teacher = get_object_or_404(Teacher, pk=request.POST.get("teacher"), school=school)
            Absence.objects.get_or_create(
                school=school, date=date, teacher=teacher, defaults={"reason": request.POST.get("reason", "")}
            )
        elif action == "delete":
            Absence.objects.filter(pk=request.POST.get("absence"), school=school).delete()
        elif action == "save":
            absence = get_object_or_404(Absence, pk=request.POST.get("absence"), school=school)
            saved = substitutes.save_assignments(absence, timetable, request.POST)
            messages.success(request, f"{saved} ders saati için vekil kaydedildi.")
        return redirect(f"{reverse('timetable:substitutions', args=[school.pk])}?tarih={date.isoformat()}")

    weekday_ok = date.weekday() < school.days_per_week
    plan = substitutes.day_plan(school, timetable, date) if timetable and weekday_ok else []
    return render(
        request,
        "timetable/substitutions.html",
        _nav(
            school,
            "subs",
            date=date,
            prev_date=date - datetime.timedelta(days=1),
            next_date=date + datetime.timedelta(days=1),
            timetable=timetable,
            plan=plan,
            teachers=school.teachers.all(),
            weekday_ok=weekday_ok,
            day_name=school.day_names[date.weekday()] if weekday_ok else "",
        ),
    )


# --- JSON API ----------------------------------------------------------------------------------


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


def api_grid(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    return JsonResponse(grid_data(timetable, request.GET.get("tur", "sinif")))


def api_status(request, pk):
    timetable = refresh_stale(get_object_or_404(Timetable, pk=pk))
    elapsed = (timezone.now() - timetable.started_at).total_seconds() if timetable.started_at else 0
    return JsonResponse(
        {
            "status": timetable.status,
            "elapsed": round(elapsed, 1),
            "time_limit": timetable.time_limit,
            "progress": jobs.progress(timetable.pk) or timetable.report.get("progress", {}),
        }
    )


@require_POST
def api_repair(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    if not timetable.has_grid:
        return JsonResponse({"ok": False, "message": "Bu program düzenlenemez."}, status=400)
    return JsonResponse(repair_timetable(timetable))


def _card(pk):
    return get_object_or_404(Card.objects.select_related("timetable__school"), pk=pk)


def api_card_options(request, pk):
    card = _card(pk)
    return JsonResponse({"ok": True, "options": editing.Board(card.timetable).options(card.id)})


@require_POST
def api_card_move(request, pk):
    card = _card(pk)
    body = _json_body(request)
    try:
        day, period = int(body["day"]), int(body["period"])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({"ok": False, "message": "Geçersiz hedef."}, status=400)
    if card.locked:
        return JsonResponse({"ok": False, "message": "Kilitli kart taşınamaz."}, status=400)
    result = editing.move_card(card, day, period)
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_card_unplace(request, pk):
    result = editing.unplace_card(_card(pk))
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_card_lock(request, pk):
    card = _card(pk)
    card.locked = not card.locked
    card.save(update_fields=["locked"])
    return JsonResponse({"ok": True, "locked": card.locked, "message": "Kart kilitlendi." if card.locked else "Kilit açıldı."})
