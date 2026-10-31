"""Hesap bildirimleri: olaylardan bildirim üretir, merkezden duyuru gönderir.

Bildirim yazmak hiçbir zaman asıl işi bozmamalı: send() hatayı yutar (ör. tablo yokken)."""

import uuid

from django.contrib.auth.models import User
from django.urls import reverse

from .models import Membership, Notification

M = Membership


def send(users, title, body="", url="", level=Notification.INFO, sender=None, broadcast=""):
    """Bildirimi her alıcıya yazar. users: kullanıcılar ya da kimlikleri. Dönüş: yazılan sayı."""
    ids = {u if isinstance(u, int) else u.pk for u in users if u is not None}
    if sender is not None:
        ids.discard(sender.pk)  # kendi yaptığı işin bildirimi gelmez
    try:
        Notification.objects.bulk_create(
            Notification(user_id=i, title=title[:200], body=body, url=url[:300], level=level, sender=sender, broadcast=broadcast)
            for i in ids
        )
    except Exception:  # bildirim yazılamadı diye işlem durmasın
        return 0
    return len(ids)


def managers(school, perm=M.DATA):
    """Programda bu yetkiye sahip kurum üyeleri (program kısıtı varsa ona uyan); yoksa merkez yöneticileri."""
    out = []
    for membership in M.objects.filter(institution_id=school.institution_id).select_related("user").prefetch_related("programs"):
        allowed = {p.pk for p in membership.programs.all()}
        if perm in membership.perms and (not allowed or school.pk in allowed) and membership.user.is_active:
            out.append(membership.user)
    return out or list(User.objects.filter(is_superuser=True, is_active=True))


def broadcast(sender, title, body="", url="", level=Notification.INFO, institution=None):
    """Merkezden duyuru: tüm etkin kullanıcılara ya da bir kurumun üyelerine. Dönüş: alıcı sayısı."""
    users = User.objects.filter(is_active=True)
    if institution is not None:
        users = users.filter(memberships__institution=institution)
    key = str(uuid.uuid4())
    recipients = list(users.distinct())
    try:
        Notification.objects.bulk_create(
            Notification(user=u, title=title[:200], body=body, url=url[:300], level=level, sender=sender, broadcast=key)
            for u in recipients
        )
    except Exception:
        return 0
    return len(recipients)


# --- olaylar -------------------------------------------------------------------------------------

def generation_finished(timetable):
    """Üretimi başlatana: program hazır / bulunamadı."""
    user_id = (timetable.report or {}).get("by")
    if not user_id:
        return
    url = reverse("timetable:timetable_detail", args=[timetable.pk])
    if timetable.status == timetable.FAILED:
        send([user_id], f"Program üretilemedi: {timetable.name}", (timetable.report or {}).get("error", ""), url, Notification.ERROR)
    elif timetable.mode == timetable.RELAXED and (timetable.report or {}).get("strict_failed"):
        send([user_id], f"Program taslak olarak hazır: {timetable.name}",
             "Kesin kurallarla program bulunamadı; kuralları esneterek en yakın taslak çıkarıldı. Nedenler rapor sayfasında.",
             url, Notification.WARNING)
    else:
        send([user_id], f"Program hazır: {timetable.name}", f"{timetable.school} · ceza {timetable.objective or 0}", url,
             Notification.SUCCESS)


def submission_sent(submission, user):
    school = submission.department.school
    send(managers(school), f"{submission.department.name} bölümü ders dağılımı önerisi gönderdi",
         submission.message[:300], reverse("timetable:departments", args=[school.pk]) + f"?bolum={submission.department_id}",
         Notification.INFO, sender=user)


def submission_decided(submission, user):
    approved = submission.status == submission.APPROVED
    send([submission.updated_by], f"{submission.department.name} önerisi {'onaylandı' if approved else 'düzeltme için geri gönderildi'}",
         submission.reply[:300], reverse("timetable:department_portal", args=[submission.department_id]),
         Notification.SUCCESS if approved else Notification.WARNING, sender=user)


def request_sent(req, user, kind="müsaitlik"):
    school = req.school
    send(managers(school), f"{req.teacher.full_name}: yeni {kind} isteği", (getattr(req, "reason", "") or "")[:300],
         reverse("timetable:teacher_requests", args=[school.pk]), Notification.INFO, sender=user)


def request_decided(req, user, kind="müsaitlik"):
    approved = req.status == req.APPROVED
    send([req.requested_by], f"{kind.capitalize()} isteğiniz {'onaylandı' if approved else 'reddedildi'}",
         (req.note or "")[:300], reverse("timetable:my_requests"),
         Notification.SUCCESS if approved else Notification.WARNING, sender=user)
