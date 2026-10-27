import datetime
import json
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from . import report_excel as report_excel_module
from . import access, analysis, asc_xml, duty, editing, excel, jobs, refs, reports, substitutes, versions
from .demo import create_demo_school
from .grid import KINDS, card_payload, grid_data, room_names
from .models import Absence, Card, Duty, DutyPlace, LessonRef, ReportPreset, School, Teacher, Timetable, TimetableVersion
from .services import check_school, refresh_stale, repair_timetable, request_stop, start_generation, verify_timetable

KIND_LABELS = {"sinif": "Sınıflar", "ogretmen": "Öğretmenler", "derslik": "Derslikler"}


def _nav(school, nav, **extra):
    latest = school.timetables.exclude(status__in=[Timetable.FAILED, Timetable.RUNNING]).first()
    return {"school": school, "nav": nav, "latest_timetable": latest, **extra}


# --- sayfalar ----------------------------------------------------------------------------------


def school_list(request):
    """Kurumlarım: her kurumun görünür programları."""
    schools = access.visible_schools(request.user).annotate(
        n_classes=Count("classes", distinct=True),
        n_teachers=Count("teachers", distinct=True),
        n_timetables=Count("timetables", distinct=True),
    ).select_related("institution", "active_timetable").order_by("name")
    groups = {}
    for school in schools:
        groups.setdefault(school.institution, []).append(school)
    for institution in access.visible_institutions(request.user):
        groups.setdefault(institution, [])
    institutions = [
        {"institution": inst, "programs": progs, "perms": access.institution_permissions(request.user, inst)}
        for inst, progs in sorted(groups.items(), key=lambda kv: kv[0].name)
    ]
    return render(request, "timetable/school_list.html", {"institutions": institutions})


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
    if timetable.has_grid:
        # Açılışta, son versiyondan beri değişiklik varsa otomatik versiyon alınır.
        versions.autosave(timetable, request.user, note="Açılışta otomatik kayıt", force=True)
    config = {
        "timetable": timetable.pk,
        "canEdit": "program" in getattr(request, "school_perms", set()),
        "running": timetable.is_running,
        "hasGrid": timetable.has_grid,
        "statusUrl": reverse("timetable:api_status", args=[timetable.pk]),
        "gridUrl": reverse("timetable:api_grid", args=[timetable.pk]),
        "repairUrl": reverse("timetable:api_repair", args=[timetable.pk]),
        "optionsUrl": reverse("timetable:api_card_options", args=[0]),
        "moveUrl": reverse("timetable:api_card_move", args=[0]),
        "unplaceUrl": reverse("timetable:api_card_unplace", args=[0]),
        "lockUrl": reverse("timetable:api_card_lock", args=[0]),
        "undoUrl": reverse("timetable:api_undo", args=[timetable.pk]),
        "redoUrl": reverse("timetable:api_redo", args=[timetable.pk]),
        "bulkUrl": reverse("timetable:api_bulk", args=[timetable.pk]),
        "infoUrl": reverse("timetable:api_card_info", args=[0]),
        "roomUrl": reverse("timetable:api_card_room", args=[0]),
        "quickUrl": reverse("timetable:api_lesson_quick", args=[0]),
        "rowUrl": reverse("timetable:api_row_action", args=[timetable.pk]),
        "cellUrl": reverse("timetable:api_cell_candidates", args=[timetable.pk]),
        "printUrl": reverse("timetable:print", args=[timetable.pk]),
        "versionsUrl": reverse("timetable:api_versions", args=[timetable.pk]),
        "versionUrl": reverse("timetable:api_version", args=[0]),
        "lessonsUrl": reverse("timetable:lessons", args=[school.pk]),
        "entityUrl": {
            "sinif": reverse("timetable:data_edit", args=[school.pk, "siniflar", 0]),
            "ogretmen": reverse("timetable:data_edit", args=[school.pk, "ogretmenler", 0]),
            "derslik": reverse("timetable:data_edit", args=[school.pk, "derslikler", 0]),
        },
        "days": school.day_names,
        "periodCount": school.periods.count(),
        "versions": [
            {"id": t.pk, "name": f"{t.name} · {timezone.localtime(t.created_at):%d.%m %H:%M}"}
            for t in school.timetables.exclude(pk=timetable.pk)
            if t.has_grid
        ],
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


@xframe_options_sameorigin
def print_view(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    kind = request.GET.get("tur", "sinif")
    summary = request.GET.get("ozet") == "1"
    if kind not in KINDS:
        kind = "sinif"
    options = {
        "days_as_rows": request.GET.get("gunler") == "satir",
        "show_detail": request.GET.get("ayrinti", "1") != "0",
        "show_room": request.GET.get("derslik", "1") != "0",
    }
    school = timetable.school
    periods = list(school.periods.all())
    names = room_names(school)
    cards = [
        card_payload(c, kind, names)
        for c in timetable.cards.filter(day__isnull=False)
        .select_related("lesson__subject", "classroom")
        .prefetch_related("lesson__classes", "lesson__teachers", "lesson__groups")
    ]
    objects = list(getattr(school, KINDS[kind]).all())
    if kind == "sinif":
        objects = list(school.classes.select_related("class_teacher", "home_classroom"))
    only = request.GET.get("id")
    if only:
        objects = [o for o in objects if str(o.pk) == only]

    def at(mine, d, p):
        return [c for c in mine if c["day"] == d and c["period"] <= p < c["period"] + c["length"]]

    pages = []
    for obj in objects:
        mine = [c for c in cards if obj.id in c["rows"]]
        if options["days_as_rows"]:
            rows = [{"head": day, "sub": "", "cells": [at(mine, d, p.index) for p in periods]} for d, day in enumerate(school.day_names)]
        else:
            rows = [
                {
                    "head": f"{period.index + 1}.",
                    "sub": f"{period.start_time:%H:%M}–{period.end_time:%H:%M}" if period.start_time and period.end_time else "",
                    "cells": [at(mine, d, period.index) for d in range(school.days_per_week)],
                }
                for period in periods
            ]
        info = []
        if kind == "ogretmen":
            title = f"{obj.first_name} {obj.last_name}"
            info.append(f"Haftalık {sum(c['length'] for c in mine)} saat")
        else:
            title = (obj.short or obj.name) if kind == "sinif" else str(obj)
            if kind == "sinif":
                if obj.short and obj.short != obj.name:
                    info.append(obj.name)
                if obj.class_teacher:
                    info.append(f"Sınıf öğretmeni: {obj.class_teacher.full_name}")
                if obj.home_classroom:
                    info.append(f"Derslik: {obj.home_classroom}")
        pages.append({"title": title, "info": info, "rows": rows})

    columns = [p for p in periods] if options["days_as_rows"] else school.day_names
    overview = None
    if summary:
        overview = []
        for obj, page in zip(objects, pages):
            mine = [c for c in cards if obj.id in c["rows"]]
            cells = []
            for d in range(school.days_per_week):
                p = 0
                while p < len(periods):
                    starting = [c for c in mine if c["day"] == d and c["period"] == p]
                    span = max((c["length"] for c in starting), default=1)
                    covered = at(mine, d, p)
                    cells.append({"cards": starting or ([] if not covered else covered), "span": span, "day_start": p == 0})
                    p += span
            overview.append({"title": page["title"], "cells": cells})
    return render(
        request,
        "timetable/print.html",
        {
            "timetable": timetable,
            "school": school,
            "pages": pages,
            "overview": overview,
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "days": school.day_names,
            "periods": periods,
            "columns": columns,
            "options": options,
            "summary": summary,
            "embedded": request.GET.get("gomulu") == "1",
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


# --- nöbet çizelgesi ---------------------------------------------------------------------------


def _int_or(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def duties(request, pk):
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_place":
            name = (request.POST.get("name") or "").strip()
            if name:
                DutyPlace.objects.create(
                    school=school, name=name[:100], teachers_per_day=max(1, _int_or(request.POST.get("teachers_per_day"), 1)),
                    order=school.duty_places.count(),
                )
                messages.success(request, f"Nöbet yeri eklendi: {name}")
        elif action == "update_place":
            place = get_object_or_404(DutyPlace, pk=request.POST.get("place"), school=school)
            place.name = (request.POST.get("name") or place.name).strip()[:100]
            place.teachers_per_day = max(1, _int_or(request.POST.get("teachers_per_day"), place.teachers_per_day))
            days = sorted({d for d in (_int_or(x, -1) for x in request.POST.getlist("days")) if 0 <= d < school.days_per_week})
            if not days:
                messages.error(request, "Nöbet yeri için en az bir gün seçin.")
            else:
                place.days = [] if len(days) == school.days_per_week else days
                place.save()
                Duty.objects.filter(place=place).exclude(day__in=days).delete()
                messages.success(request, f"{place.name} güncellendi.")
        elif action == "delete_place":
            DutyPlace.objects.filter(pk=request.POST.get("place"), school=school).delete()
        elif action == "settings":
            school.duties_per_teacher = max(0, _int_or(request.POST.get("duties_per_teacher"), school.duties_per_teacher))
            school.save(update_fields=["duties_per_teacher"])
            messages.success(request, "Nöbet ayarı kaydedildi.")
        elif action == "generate":
            result = duty.generate(school)
            (messages.success if result["ok"] else messages.error)(request, result["message"])
        elif action == "clear":
            Duty.objects.filter(place__school=school).delete()
            messages.info(request, "Tüm nöbetler silindi.")
        elif action == "set":
            place = get_object_or_404(DutyPlace, pk=request.POST.get("place"), school=school)
            day = _int_or(request.POST.get("day"), -1)
            if 0 <= day < school.days_per_week:
                ids = {_int_or(x, None) for x in request.POST.getlist("teachers")} - {None}
                valid = set(school.teachers.filter(pk__in=ids).values_list("pk", flat=True))
                Duty.objects.filter(place=place, day=day).exclude(teacher_id__in=valid).delete()
                existing = set(Duty.objects.filter(place=place, day=day).values_list("teacher_id", flat=True))
                Duty.objects.bulk_create(Duty(place=place, day=day, teacher_id=t) for t in valid - existing)
        return redirect("timetable:duties", pk=school.pk)
    data = duty.roster(school)
    return render(request, "timetable/duties.html", _nav(school, "duties", **data, teachers_all=list(school.teachers.all())))


def duties_print(request, pk):
    school = get_object_or_404(School, pk=pk)
    return render(request, "timetable/duties_print.html", {"school": school, **duty.roster(school)})


# --- JSON API ----------------------------------------------------------------------------------


def _json_body(request):
    try:
        return json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return {}


def api_grid(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    data = grid_data(timetable, request.GET.get("tur", "sinif"))
    data["history"] = editing.history_info(timetable)
    other_id = request.GET.get("karsilastir")
    if other_id and other_id.isdigit():
        other = Timetable.objects.filter(pk=other_id, school=timetable.school).first()
        if other is not None:
            data["compare"] = {"name": other.name, **analysis.compare(timetable, other)}
    return JsonResponse(data)


@require_POST
def api_undo(request, pk):
    result = editing.undo(get_object_or_404(Timetable, pk=pk))
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_redo(request, pk):
    result = editing.redo(get_object_or_404(Timetable, pk=pk))
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_bulk(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    if not timetable.has_grid:
        return JsonResponse({"ok": False, "message": "Bu program düzenlenemez."}, status=400)
    body = _json_body(request)
    result = editing.bulk_action(timetable, body.get("action"), body.get("a"), body.get("b"))
    return JsonResponse(result, status=200 if result["ok"] else 400)


def api_versions(request, pk):
    timetable = get_object_or_404(Timetable, pk=pk)
    if request.method == "POST":
        note = (_json_body(request).get("note") or "").strip()
        version = versions.save_version(timetable, user=request.user, note=note or "Elle kayıt")
        return JsonResponse({"ok": True, "message": f"#{version.number} versiyonu kaydedildi."})
    include_auto = request.GET.get("oto") != "0"
    return JsonResponse({"ok": True, "versions": versions.listing(timetable, include_auto),
                         "auto_count": timetable.versions.filter(auto=True).count()})


def api_version(request, pk):
    """GET: önizleme. POST action=restore: geri yükle, action=open: ayrı program olarak aç."""
    version = get_object_or_404(TimetableVersion.objects.select_related("timetable__school"), pk=pk)
    timetable = version.timetable
    if request.method == "GET":
        return JsonResponse({"ok": True, **versions.preview(version)})
    action = _json_body(request).get("action")
    if action == "restore":
        return JsonResponse(versions.restore(timetable, version, request.user))
    if action == "open":
        copy = Timetable.objects.create(
            school=timetable.school, name=f"{timetable.name} – #{version.number}", status=timetable.status,
            mode=timetable.mode, time_limit=timetable.time_limit,
        )
        lessons = {c.id: (c.lesson_id, c.length) for c in timetable.cards.all()}
        Card.objects.bulk_create(
            Card(timetable=copy, lesson_id=lessons[cid][0], length=lessons[cid][1], day=d, period=p, classroom_id=room,
                 extra_rooms=extra, locked=locked)
            for cid, d, p, room, extra, locked in version.cards if cid in lessons
        )
        versions.save_version(copy, user=request.user, note=f"{timetable.name} #{version.number} kopyası")
        return JsonResponse({"ok": True, "message": "Ayrı program olarak açıldı.", "url": reverse("timetable:timetable_detail", args=[copy.pk])})
    return JsonResponse({"ok": False, "message": "Bilinmeyen işlem."}, status=400)


def reports_page(request, pk):
    """Rapor tasarımı: solda ayarlar, sağda canlı ön izleme; ayarlar şablon olarak kaydedilebilir."""
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    if request.method == "POST":
        if request.POST.get("action") == "delete_preset":
            ReportPreset.objects.filter(pk=request.POST.get("preset"), school=school).delete()
            messages.info(request, "Rapor şablonu silindi.")
        else:
            name = (request.POST.get("name") or "").strip()[:100]
            params = {k: request.POST.getlist(k) if k in ("icerik", "secim") else request.POST.get(k, "") for k in reports.PARAM_KEYS}
            params["icerik_set"] = "1"
            if name:
                ReportPreset.objects.update_or_create(school=school, name=name, defaults={"params": params})
                messages.success(request, f"Rapor şablonu kaydedildi: {name}")
        return redirect("timetable:reports", pk=timetable.pk)
    o = reports.options(request.GET)
    presets = [{"preset": p, "query": urlencode(p.params, doseq=True)} for p in school.report_presets.all()]
    return render(
        request,
        "timetable/reports.html",
        _nav(
            school, "reports", timetable=timetable, o=o, types=reports.TYPES, kinds=reports.KIND_LABELS,
            content=reports.CONTENT, choices=reports.selectable(school, o["varlik"]), presets=presets,
            query=request.GET.urlencode(), days=school.day_names,
        ),
    )


@xframe_options_sameorigin
def report_render(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    data = reports.build(timetable, reports.options(request.GET))
    data["embedded"] = request.GET.get("gomulu") == "1"
    return render(request, "timetable/report.html", data)


def report_excel(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    o = reports.options(request.GET)
    data = reports.build(timetable, o)
    response = HttpResponse(report_excel_module.build(data), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="rapor-{o["tur"]}-{timetable.pk}.xlsx"'
    return response


def statistics(request, pk):
    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    return render(
        request,
        "timetable/statistics.html",
        _nav(school, "timetable", timetable=timetable, stats=analysis.statistics(timetable)),
    )


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
    mode = body.get("mode", "displace")
    if mode not in ("displace", "ignore", "swap", "ask"):
        mode = "displace"
    result = editing.move_card(card, day, period, mode)
    if result.get("ask"):
        return JsonResponse(result, status=409)
    return JsonResponse(result, status=200 if result["ok"] else 400)


def api_card_info(request, pk):
    """Sağ tık menüsü için kartın ilişkili kayıtları, derslik durumları ve ilgili ihlaller."""
    card = _card(pk)
    lesson = card.lesson
    board = editing.Board(card.timetable)
    label = board.problem.label("lesson", lesson.id)
    violations, _ = verify_timetable(card.timetable)
    school = card.timetable.school
    return JsonResponse({
        "ok": True,
        "label": label,
        "lesson": lesson.id,
        "lesson_url": reverse("timetable:lesson_edit", args=[school.pk, lesson.id]),
        "subject": {"id": lesson.subject_id, "name": lesson.subject.name,
                    "url": reverse("timetable:data_edit", args=[school.pk, "ders-adlari", lesson.subject_id])},
        "teachers": [{"id": t.id, "name": t.full_name, "url": reverse("timetable:data_edit", args=[school.pk, "ogretmenler", t.id])}
                     for t in lesson.teachers.all()],
        "classes": [{"id": c.id, "name": c.short or c.name, "url": reverse("timetable:data_edit", args=[school.pk, "siniflar", c.id])}
                    for c in lesson.classes.all()],
        "rooms": board.room_choices(card.id),
        "all_teachers": [{"id": t.id, "name": t.full_name} for t in school.teachers.all()],
        "violations": [v.message for v in violations if label in v.message],
    })


@require_POST
def api_card_room(request, pk):
    card = _card(pk)
    room = _json_body(request).get("room")
    result = editing.set_room(card, int(room) if str(room).isdigit() else None)
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_lesson_quick(request, pk):
    """Hızlı değişiklik: dersin öğretmenlerini değiştirir (aSc "Hızlı Değişiklik Yap")."""
    card = _card(pk)
    school = card.timetable.school
    ids = [int(x) for x in _json_body(request).get("teachers", []) if str(x).isdigit()]
    teachers = list(school.teachers.filter(pk__in=ids))
    card.lesson.teachers.set(teachers)
    names = ", ".join(t.full_name for t in teachers) or "öğretmensiz"
    return JsonResponse({"ok": True, "message": f"Dersin öğretmeni güncellendi: {names}. Bu dersin tüm kartları etkilenir."})


@require_POST
def api_row_action(request, pk):
    timetable = get_object_or_404(Timetable, pk=pk)
    body = _json_body(request)
    if body.get("kind") not in KINDS or not str(body.get("row", "")).isdigit():
        return JsonResponse({"ok": False, "message": "Geçersiz satır."}, status=400)
    result = editing.row_action(timetable, body["kind"], int(body["row"]), body.get("action"))
    return JsonResponse(result, status=200 if result["ok"] else 400)


def api_cell_candidates(request, pk):
    timetable = get_object_or_404(Timetable, pk=pk)
    try:
        kind, row = request.GET["tur"], int(request.GET["satir"])
        day, period = int(request.GET["gun"]), int(request.GET["saat"])
    except (KeyError, ValueError):
        return JsonResponse({"ok": False, "message": "Geçersiz hücre."}, status=400)
    if kind not in KINDS:
        return JsonResponse({"ok": False, "message": "Geçersiz görünüm."}, status=400)
    return JsonResponse({"ok": True, "cards": editing.cell_candidates(timetable, kind, row, day, period)})


@require_POST
def api_card_unplace(request, pk):
    result = editing.unplace_card(_card(pk))
    return JsonResponse(result, status=200 if result["ok"] else 400)


@require_POST
def api_card_lock(request, pk):
    return JsonResponse(editing.toggle_lock(_card(pk)))


# --- ÜYBS referansları -------------------------------------------------------------------------


def _ref_timetable(school, value):
    timetable = None
    if value and str(value).isdigit():
        timetable = school.timetables.filter(pk=value).first()
    return timetable or school.active_timetable or school.timetables.filter(status__in=[Timetable.OK, Timetable.PARTIAL]).first()


def lesson_refs(request, pk):
    """ÜYBS referans ekranı: her kısımda her dersin her saatine referans; programdaki yeri yanında."""
    school = get_object_or_404(School, pk=pk)
    class_id = request.GET.get("sinif") or request.POST.get("sinif") or ""
    school_class = school.classes.filter(pk=class_id).first() if class_id.isdigit() else None
    timetable = _ref_timetable(school, request.GET.get("program") or request.POST.get("program"))
    back = reverse("timetable:lesson_refs", args=[school.pk]) + "?" + urlencode(
        {k: v for k, v in {"sinif": class_id, "program": timetable.pk if timetable else ""}.items() if v}
    )
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            n = refs.save_form(school, request.POST)
            messages.success(request, f"{n} referans kaydedildi.")
        elif action == "auto":
            try:
                n = refs.auto_number(
                    school, timetable, request.POST.get("start", "1001"), max(1, int(request.POST.get("step") or 1)),
                    overwrite=request.POST.get("overwrite") == "1", school_class=school_class,
                    order=request.POST.get("order", "program"),
                )
                messages.success(request, f"{n} saate referans verildi.")
            except ValueError as exc:
                messages.error(request, str(exc))
        elif action == "import":
            n, errors = refs.import_text(school, request.POST.get("text", ""))
            messages.success(request, f"{n} referans aktarıldı.")
            for error in errors[:10]:
                messages.error(request, error)
            if len(errors) > 10:
                messages.error(request, f"… ve {len(errors) - 10} hata daha.")
        elif action == "clear":
            qs = LessonRef.objects.filter(lesson__school=school)
            if school_class:
                qs = qs.filter(school_class=school_class)
            n = qs.count()
            qs.delete()
            messages.info(request, f"{n} referans silindi.")
        return redirect(back)
    rows = refs.table(school, timetable, school_class)
    total = sum(len(r["slots"]) for r in rows)
    filled = sum(1 for r in rows for s in r["slots"] if s["ref"])
    return render(request, "timetable/refs.html", _nav(
        school, "refs", rows=rows, classes=list(school.classes.all()), school_class=school_class,
        timetable=timetable, timetables=[t for t in school.timetables.all() if t.has_grid],
        total=total, filled=filled,
    ))
