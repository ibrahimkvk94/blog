"""Öğretmen istek formu: öğretmen kendi hesabıyla "şu gün/saat gelemem" bildirir, program sorumlusu
onaylayınca istek öğretmenin müsaitliğine yazılır.

Öğretmen, kullanıcı hesabı öğretmen kartına bağlıysa (Teacher.user) istekte bulunabilir. Bir öğretmenin
aynı anda tek bekleyen isteği olur: yeniden gönderince bekleyen istek güncellenir.
"""

from django.db import transaction
from django.utils import timezone

from .models import Availability, AvailabilityRequest, Teacher

STATES = ("no", "maybe", "")
STATE_LABELS = {"no": "gelemem", "maybe": "tercih etmem", "": "gelebilirim"}

R = AvailabilityRequest


def linked_teachers(user):
    if not user.is_authenticated:
        return Teacher.objects.none()
    return Teacher.objects.filter(user=user).select_related("school__institution").order_by("school__name")


def school_closed(school):
    return set(Availability.objects.filter(school=school, state=Availability.NO,
                                           **{f"{f}__isnull": True for f in Availability.TARGET_FIELDS})
               .values_list("day", "period"))


def current_states(teacher):
    """{(gün, saat): "no" | "maybe"} — öğretmenin onaylı (kayıtlı) müsaitliği."""
    return {(d, p): s for d, p, s in teacher.availabilities.values_list("day", "period", "state")}


def pending_of(teacher):
    return teacher.availability_requests.filter(status=R.PENDING).first()


def grid(teacher, desired=None):
    """Izgara satırları: gün başına hücreler {day, period, state, current, closed, changed}."""
    school = teacher.school
    periods = list(school.periods.all())
    closed = school_closed(school)
    current = current_states(teacher)
    desired = desired if desired is not None else current
    rows = []
    for d, name in enumerate(school.day_names):
        cells = []
        for p in periods:
            key = (d, p.index)
            state = desired.get(key, "")
            cells.append({"day": d, "period": p.index, "state": state, "current": current.get(key, ""),
                          "closed": key in closed, "changed": state != current.get(key, "")})
        rows.append({"day": name, "cells": cells})
    return {"periods": periods, "rows": rows}


def desired_with_pending(teacher):
    desired = dict(current_states(teacher))
    pending = pending_of(teacher)
    if pending:
        for d, p, state in pending.changes:
            if state:
                desired[(d, p)] = state
            else:
                desired.pop((d, p), None)
    return desired


def parse_cells(post, teacher):
    """Formdaki "h-<gün>-<saat>" = no|maybe|"" alanlarından istenen durum."""
    school = teacher.school
    days, periods = len(school.day_names), {p.index for p in school.periods.all()}
    desired = {}
    for key, value in post.items():
        if not key.startswith("h-") or value not in ("no", "maybe"):
            continue
        parts = key[2:].split("-")
        if len(parts) == 2 and all(x.isdigit() for x in parts):
            d, p = map(int, parts)
            if d < days and p in periods:
                desired[(d, p)] = value
    return desired


def diff(teacher, desired):
    current = current_states(teacher)
    closed = school_closed(teacher.school)
    changes = []
    for key in sorted(set(current) | set(desired)):
        if key in closed:
            continue  # okul genelinde kapalı saat: zaten ders konmaz
        before, after = current.get(key, ""), desired.get(key, "")
        if before != after:
            changes.append([key[0], key[1], after])
    return changes


def submit(teacher, user, desired, reason):
    """İsteği kaydeder (bekleyen varsa günceller). Dönüş: (istek ya da None, mesaj)."""
    changes = diff(teacher, desired)
    pending = pending_of(teacher)
    if not changes:
        if pending:
            pending.status, pending.decided_at = R.WITHDRAWN, timezone.now()
            pending.save(update_fields=["status", "decided_at"])
            return None, "Kayıtlı müsaitliğinizle aynı; bekleyen isteğiniz geri alındı."
        return None, "Değişiklik yok: kayıtlı müsaitliğinizden farklı bir saat seçin."
    if pending:
        pending.changes, pending.reason, pending.requested_by = changes, reason, user
        pending.save(update_fields=["changes", "reason", "requested_by"])
        return pending, "Bekleyen isteğiniz güncellendi."
    req = R.objects.create(school=teacher.school, teacher=teacher, requested_by=user, changes=changes, reason=reason)
    return req, "İsteğiniz program sorumlusuna iletildi."


def withdraw(req):
    if req.status == R.PENDING:
        req.status, req.decided_at = R.WITHDRAWN, timezone.now()
        req.save(update_fields=["status", "decided_at"])


def approve(req, user, note=""):
    with transaction.atomic():
        for d, p, state in req.changes:
            Availability.objects.filter(school=req.school, teacher=req.teacher, day=d, period=p).delete()
            if state:
                Availability.objects.create(school=req.school, teacher=req.teacher, day=d, period=p, state=state)
        req.status, req.decided_by, req.decided_at, req.note = R.APPROVED, user, timezone.now(), note
        req.save(update_fields=["status", "decided_by", "decided_at", "note"])


def reject(req, user, note=""):
    req.status, req.decided_by, req.decided_at, req.note = R.REJECTED, user, timezone.now(), note
    req.save(update_fields=["status", "decided_by", "decided_at", "note"])


def describe(req):
    """İstekteki değişiklikler okunur metin olarak: [("Pazartesi 3. saat (10:00–10:40)", "gelemem"), ...]."""
    school = req.school
    days = school.day_names
    periods = {p.index: p for p in school.periods.all()}
    out = []
    for d, p, state in sorted(req.changes):
        period = periods.get(p)
        span = period.span(d) if period else ""
        out.append({"label": f"{days[d] if d < len(days) else d + 1} {p + 1}. saat", "span": span,
                    "state": state, "text": STATE_LABELS.get(state, state)})
    return out


def conflicts(req, timetable):
    """Onaylanırsa programdaki hangi derslerin öğretmenin gelemeyeceği saate düştüğü."""
    if timetable is None:
        return []
    blocked = {(d, p) for d, p, state in req.changes if state == "no"}
    if not blocked:
        return []
    days = req.school.day_names
    out = []
    for card in timetable.cards.filter(day__isnull=False, lesson__teachers=req.teacher).select_related("lesson__subject").prefetch_related("lesson__classes"):
        hit = [card.period + i for i in range(card.length) if (card.day, card.period + i) in blocked]
        if hit:
            classes = ", ".join(c.short or c.name for c in card.lesson.classes.all())
            out.append(f"{days[card.day]} {hit[0] + 1}. saat: {card.lesson.subject.short or card.lesson.subject.name} ({classes})")
    return out
