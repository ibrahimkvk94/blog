"""Öğretmen istek formu: öğretmen kendi hesabıyla "şu gün/saat gelemem" bildirir, program sorumlusu
onaylayınca istek öğretmenin müsaitliğine yazılır.

Öğretmen, kullanıcı hesabı öğretmen kartına bağlıysa (Teacher.user) istekte bulunabilir. Bir öğretmenin
aynı anda tek bekleyen isteği olur: yeniden gönderince bekleyen istek güncellenir.
"""

from django.db import transaction
from django.utils import timezone

from . import notifications
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
    notifications.request_sent(req, user)
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
    notifications.request_decided(req, user)


def reject(req, user, note=""):
    req.status, req.decided_by, req.decided_at, req.note = R.REJECTED, user, timezone.now(), note
    req.save(update_fields=["status", "decided_by", "decided_at", "note"])
    notifications.request_decided(req, user)


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


# --- tarihli izin / rapor -------------------------------------------------------------------------

MAX_LEAVE_DAYS = 120


def parse_leave(post, teacher):
    """Formdan izin bildirimi alanları. Dönüş: (alanlar, hata)."""
    import datetime

    from .models import LeaveRequest

    try:
        start = datetime.date.fromisoformat(post.get("baslangic", ""))
        end = datetime.date.fromisoformat(post.get("bitis") or post.get("baslangic", ""))
    except ValueError:
        return None, "Geçerli bir tarih girin."
    if end < start:
        return None, "Bitiş tarihi başlangıçtan önce olamaz."
    if (end - start).days > MAX_LEAVE_DAYS:
        return None, f"En fazla {MAX_LEAVE_DAYS} günlük bildirim yapılabilir."
    indexes = {p.index for p in teacher.school.periods.all()}
    periods = [] if post.get("tum_gun") else sorted({int(p) for p in post.getlist("saat") if p.isdigit() and int(p) in indexes})
    if not post.get("tum_gun") and not periods:
        return None, "“Tüm gün” seçin ya da saatleri işaretleyin."
    kind = post.get("tur") if post.get("tur") in dict(LeaveRequest.KINDS) else "izin"
    return {"start_date": start, "end_date": end, "periods": periods, "kind": kind,
            "reason": (post.get("aciklama") or "").strip()[:2000]}, None


def submit_leave(teacher, user, fields):
    from .models import LeaveRequest

    req = LeaveRequest(school=teacher.school, teacher=teacher, requested_by=user, **fields)
    if not req.school_days():
        return None, "Seçilen aralıkta okul günü yok."
    req.save()
    notifications.request_sent(req, user, kind="izin")
    return req, "İzin bildiriminiz program sorumlusuna iletildi."


def affected_lessons(req, timetable):
    """Onaylanırsa vekil gerekecek ders saati sayısı (yayındaki programa göre)."""
    if timetable is None:
        return 0
    per_weekday = {}
    for day, period, length in timetable.cards.filter(day__isnull=False, lesson__teachers=req.teacher).values_list("day", "period", "length"):
        hours = sum(1 for i in range(length) if not req.periods or period + i in req.periods)
        per_weekday[day] = per_weekday.get(day, 0) + hours
    return sum(per_weekday.get(d.weekday(), 0) for d in req.school_days())


def approve_leave(req, user, note=""):
    """Aralıktaki her okul gününe devamsızlık yazar (var olanla birleştirir). Dönüş: gün sayısı."""
    from .models import Absence, LeaveRequest

    label = req.get_kind_display() + (f": {req.reason}" if req.reason else "")
    with transaction.atomic():
        for day in req.school_days():
            absence, created = Absence.objects.get_or_create(
                school=req.school, teacher=req.teacher, date=day, defaults={"reason": label[:200], "periods": req.periods})
            if not created:
                # Tüm gün izin her şeyi kapsar; iki kısmi izin saatleri birleşir
                absence.periods = [] if not absence.periods or not req.periods else sorted(set(absence.periods) | set(req.periods))
                absence.reason = absence.reason or label[:200]
                absence.save(update_fields=["periods", "reason"])
        req.status, req.decided_by, req.decided_at, req.note = LeaveRequest.APPROVED, user, timezone.now(), note
        req.save(update_fields=["status", "decided_by", "decided_at", "note"])
    notifications.request_decided(req, user, kind="izin")
    return len(req.school_days())


def decide_leave(req, user, status, note=""):
    req.status, req.decided_by, req.decided_at, req.note = status, user, timezone.now(), note
    req.save(update_fields=["status", "decided_by", "decided_at", "note"])
    notifications.request_decided(req, user, kind="izin")
