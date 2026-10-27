"""Herkese açık web yayını: gizli bağlantıyla giriş yapmadan programları görme (telefon uyumlu)
ve koridor ekranı için günlük vekâlet listesi. Yalnızca yayındaki sürüm gösterilir."""

import datetime
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import substitutes
from .refs import DAY_SHORT
from .grid import KINDS, card_payload, room_names
from .models import School

KIND_TITLES = {"sinif": "Sınıflar", "ogretmen": "Öğretmenler", "derslik": "Derslikler"}


def _published(token):
    school = School.objects.filter(publish_token=token, publish_enabled=True).select_related("active_timetable").first()
    if school is None or not token:
        raise Http404("Yayın bulunamadı ya da kapatıldı.")
    return school


def _kinds(school):
    return [k for k in KINDS if k != "ogretmen" or school.publish_teachers]


def _label(obj, kind):
    if kind == "ogretmen":
        return obj.full_name
    if kind == "sinif":
        return obj.short or obj.name
    return str(obj)


@login_not_required
def index(request, token):
    school = _published(token)
    groups = [
        {"kind": kind, "title": KIND_TITLES[kind],
         "items": [{"id": o.pk, "name": _label(o, kind), "sub": o.name if kind == "sinif" and o.short else ""}
                   for o in getattr(school, KINDS[kind]).all()]}
        for kind in _kinds(school)
    ]
    return render(request, "timetable/public/index.html", {"school": school, "groups": groups, "token": token})


@login_not_required
def timetable(request, token, kind, obj_id):
    school = _published(token)
    if kind not in _kinds(school):
        raise Http404
    obj = get_object_or_404(getattr(school, KINDS[kind]), pk=obj_id)
    tt = school.active_timetable
    periods = list(school.periods.all())
    days = school.day_names
    cards = []
    if tt is not None:
        names = room_names(school)
        cards = [
            card_payload(c, kind, names)
            for c in tt.cards.filter(day__isnull=False).select_related("lesson__subject", "classroom")
            .prefetch_related("lesson__classes", "lesson__teachers", "lesson__groups")
        ]
    mine = [c for c in cards if obj.id in c["rows"]]
    if not school.publish_teachers:
        for c in mine:
            c["teachers"] = ""
            c["line2"] = c["classes"] if kind != "sinif" else c["groups"]

    def at(d, p):
        return [c for c in mine if c["day"] == d and c["period"] <= p < c["period"] + c["length"]]

    week = [
        {"period": p, "cells": [at(d, p.index) for d in range(len(days))]}
        for p in periods
    ]
    today = timezone.localdate().weekday()
    by_day = [
        {"name": day, "short": DAY_SHORT[d], "index": d, "slots": [{"period": p, "cards": at(d, p.index)} for p in periods]}
        for d, day in enumerate(days)
    ]
    return render(request, "timetable/public/timetable.html", {
        "school": school, "token": token, "kind": kind, "title": _label(obj, kind),
        "subtitle": obj.name if kind == "sinif" and obj.short else "", "days": days, "week": week, "by_day": by_day,
        "today": today if today < len(days) else 0,
        "class_teacher": obj.class_teacher.full_name if kind == "sinif" and obj.class_teacher and school.publish_teachers else "",
    })


@login_not_required
def substitution_board(request, token):
    """Koridor ekranı: günün vekâlet listesi; sayfa kendini yeniler."""
    school = _published(token)
    if not school.publish_substitutions:
        raise Http404
    try:
        date = datetime.date.fromisoformat(request.GET.get("tarih") or "")
    except ValueError:
        date = timezone.localdate()
    rows = []
    if school.active_timetable and date.weekday() < school.days_per_week:
        for item in substitutes.day_plan(school, school.active_timetable, date):
            for slot in item["slots"]:
                sub = slot["current"].substitute if slot["current"] and slot["current"].substitute_id else None
                rows.append({
                    "period": slot["period"] + 1,
                    "start": slot["period_obj"].start_time if slot["period_obj"] else None,
                    "classes": slot["classes"], "groups": slot["groups"],
                    "subject": slot["card"].lesson.subject.name,
                    "absent": item["absence"].teacher.full_name if school.publish_teachers else "",
                    "substitute": (sub.full_name if school.publish_teachers else "atandı") if sub else "",
                })
    rows.sort(key=lambda r: (r["period"], r["classes"]))
    return render(request, "timetable/public/board.html", {
        "school": school, "token": token, "date": date, "rows": rows,
        "day_name": school.day_names[date.weekday()] if date.weekday() < school.days_per_week else "",
    })


def settings(request, pk):
    """Web yayını ayarları: aç/kapat, yeni bağlantı üret, seçenekler, QR kod."""
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "enable":
            if not school.publish_token:
                school.publish_token = secrets.token_urlsafe(16)
            school.publish_enabled = True
            messages.success(request, "Web yayını açıldı.")
        elif action == "disable":
            school.publish_enabled = False
            messages.info(request, "Web yayını kapatıldı; bağlantı artık çalışmaz.")
        elif action == "regenerate":
            school.publish_token = secrets.token_urlsafe(16)
            messages.success(request, "Yeni bağlantı üretildi; eski bağlantı artık çalışmaz.")
        elif action == "options":
            school.publish_teachers = request.POST.get("publish_teachers") == "1"
            school.publish_substitutions = request.POST.get("publish_substitutions") == "1"
            messages.success(request, "Yayın seçenekleri kaydedildi.")
        school.save(update_fields=["publish_token", "publish_enabled", "publish_teachers", "publish_substitutions"])
        return redirect("timetable:publish_settings", pk=school.pk)
    link = board = qr = ""
    if school.publish_token:
        link = request.build_absolute_uri(reverse("timetable:public_index", args=[school.publish_token]))
        board = request.build_absolute_uri(reverse("timetable:public_board", args=[school.publish_token]))
        try:
            import segno

            qr = segno.make(link, error="m").svg_inline(scale=5, dark="#1c2230")
        except ImportError:
            qr = ""
    from .views import _nav

    return render(request, "timetable/publish_settings.html", _nav(school, "publish", link=link, board=board, qr=qr))
