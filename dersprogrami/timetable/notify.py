"""E-posta bildirimleri: yayındaki program değişince etkilenen öğretmenlere, vekil atanınca vekile.

E-posta sunucusu ayarlı değilse (EMAIL_HOST boş) hiçbir şey gönderilmez; çağıran tarafa bildirilir.
"""

import logging
from collections import defaultdict

from django.conf import settings
from django.core.mail import EmailMessage, get_connection

from .refs import DAY_SHORT

log = logging.getLogger(__name__)


def enabled():
    return bool(getattr(settings, "EMAIL_HOST", "")) or settings.EMAIL_BACKEND != "django.core.mail.backends.smtp.EmailBackend"


def _teacher_hours(timetable):
    """{öğretmen kimliği: {(gün, saat): "DERS · sınıflar"}}"""
    hours = defaultdict(dict)
    if timetable is None:
        return hours
    for card in timetable.cards.filter(day__isnull=False).select_related("lesson__subject").prefetch_related(
        "lesson__teachers", "lesson__classes"
    ):
        subject = card.lesson.subject
        text = f"{subject.short or subject.name} · " + ", ".join(c.short or c.name for c in card.lesson.classes.all())
        for t in card.lesson.teachers.all():
            for i in range(card.length):
                hours[t.id][(card.day, card.period + i)] = text
    return hours


def changes(old, new):
    """{öğretmen kimliği: [değişiklik satırları]} — yalnızca programı değişen öğretmenler."""
    before, after = _teacher_hours(old), _teacher_hours(new)
    result = {}
    for tid in set(before) | set(after):
        a, b = before.get(tid, {}), after.get(tid, {})
        lines = []
        for cell in sorted(set(a) | set(b)):
            if a.get(cell) == b.get(cell):
                continue
            d, p = cell
            where = f"{DAY_SHORT[d]} {p + 1}. saat"
            if cell in a and cell in b:
                lines.append(f"{where}: {a[cell]} → {b[cell]}")
            elif cell in b:
                lines.append(f"{where}: yeni ders – {b[cell]}")
            else:
                lines.append(f"{where}: kaldırıldı – {a[cell]}")
        if lines:
            result[tid] = lines
    return result


def _send(messages):
    if not messages:
        return 0, []
    errors = []
    sent = 0
    try:
        with get_connection(fail_silently=False) as connection:
            for message in messages:
                try:
                    message.connection = connection
                    message.send()
                    sent += 1
                except Exception as exc:  # tek alıcının hatası diğerlerini durdurmasın
                    errors.append(f"{', '.join(message.to)}: {exc}")
    except Exception as exc:
        log.warning("E-posta sunucusuna bağlanılamadı: %s", exc)
        errors.append(f"E-posta sunucusuna bağlanılamadı: {exc}")
    return sent, errors


def publish_notices(school, old, new, link=""):
    """Yayın değişince programı değişen ve e-postası olan öğretmenlere özet gönderir.
    Dönüş: (gönderilen, e-postası olmayan değişen öğretmen sayısı, hatalar)."""
    diff = changes(old, new)
    teachers = {t.id: t for t in school.teachers.filter(id__in=diff)}
    messages, no_mail = [], 0
    for tid, lines in diff.items():
        teacher = teachers.get(tid)
        if teacher is None:
            continue
        if not teacher.email:
            no_mail += 1
            continue
        body = (
            f"Sayın {teacher.full_name},\n\n{school} için yayındaki ders programı “{new.name}” olarak güncellendi. "
            f"Programınızdaki değişiklikler:\n\n" + "\n".join(f"• {line}" for line in lines)
            + (f"\n\nGüncel programınız: {link}" if link else "") + "\n"
        )
        messages.append(EmailMessage(f"Ders programınız değişti – {school}", body, to=[teacher.email]))
    if not enabled():
        return 0, no_mail, ["E-posta sunucusu ayarlı değil (EMAIL_HOST)."] if messages else []
    sent, errors = _send(messages)
    return sent, no_mail, errors


def substitution_notices(absence, substitutions, released=()):
    """Vekâlet değişiklikleri: yeni vekile görev, görevden alınan önceki vekile iptal, etkilenen sınıfların sınıf
    öğretmenine özet. substitutions: değişen Substitution nesneleri; released: [(önceki vekil Teacher, Substitution)].
    Dönüş: (gönderilen, hatalar)."""
    school = absence.school
    date = f"{absence.date:%d.%m.%Y}"
    periods = {p.index: p for p in school.periods.all()}
    weekday = absence.date.weekday()

    def line(sub):
        card = sub.card
        period = periods.get(sub.period)
        when = f"{sub.period + 1}. saat" + (f" ({period.span(weekday)})" if period and period.span(weekday) else "")
        classes = ", ".join(c.short or c.name for c in card.lesson.classes.all())
        return f"{when} · {card.lesson.subject.name} · {classes}" + (f" · {card.classroom}" if card.classroom_id else "")

    def mail(teacher, subject, intro, lines):
        body = f"Sayın {teacher.full_name},\n\n{intro}\n\n" + "\n".join(f"• {x}" for x in sorted(lines)) + "\n"
        return EmailMessage(f"{subject} {date} – {school}", body, to=[teacher.email])

    assigned, cancelled, classes = defaultdict(list), defaultdict(list), defaultdict(list)
    for sub in substitutions:
        if sub.substitute_id and sub.substitute.email:
            assigned[sub.substitute].append(line(sub))
        for cls in sub.card.lesson.classes.all():
            teacher = cls.class_teacher
            if teacher and teacher.email and teacher.id not in (absence.teacher_id, sub.substitute_id):
                who = sub.substitute.full_name if sub.substitute_id else "vekil yok, ders boş geçecek"
                classes[teacher].append(f"{line(sub)} → {who}")
    for teacher, sub in released:
        if teacher is not None and teacher.email and teacher.id != sub.substitute_id:
            cancelled[teacher].append(line(sub))
    messages = (
        [mail(t, "Vekâlet görevi", f"{date} günü {absence.teacher.full_name} yerine şu derslere girmeniz rica olunur:", lines)
         for t, lines in assigned.items()]
        + [mail(t, "Vekâlet görevi iptal", f"{date} günü şu derslerdeki vekâlet göreviniz kaldırıldı:", lines)
           for t, lines in cancelled.items()]
        + [mail(t, "Sınıfınızda vekâlet", f"{date} günü {absence.teacher.full_name} okulda olmayacak; sınıfınızdaki dersler:", lines)
           for t, lines in classes.items()]
    )
    if not messages or not enabled():
        return 0, []
    return _send(messages)


def request_decision_notice(req, items, link=""):
    """Öğretmene müsaitlik isteğinin onaylandığını/reddedildiğini bildirir. Dönüş: (gönderilen, hatalar)."""
    teacher = req.teacher
    if not enabled() or not teacher.email:
        return 0, []
    verdict = "onaylandı" if req.status == req.APPROVED else "reddedildi"
    lines = [f"Merhaba {teacher.full_name},", "", f"{req.school} programı için gönderdiğiniz müsaitlik isteği {verdict}.", ""]
    lines += [f"- {i['label']} {i['span']}: {i['text']}" for i in items]
    if req.note:
        lines += ["", f"Yanıt: {req.note}"]
    if link:
        lines += ["", link]
    return _send([EmailMessage(f"Müsaitlik isteğiniz {verdict} – {req.school}", "\n".join(lines), to=[teacher.email])])


def leave_decision_notice(req, link=""):
    """Öğretmene izin/rapor bildiriminin onaylandığını/reddedildiğini bildirir. Dönüş: (gönderilen, hatalar)."""
    teacher = req.teacher
    if not enabled() or not teacher.email:
        return 0, []
    verdict = "onaylandı" if req.status == req.APPROVED else "reddedildi"
    lines = [f"Merhaba {teacher.full_name},", "",
             f"{req.start_date:%d.%m.%Y}–{req.end_date:%d.%m.%Y} tarihli {req.get_kind_display().lower()} bildiriminiz "
             f"({req.periods_label}) {verdict}."]
    if req.note:
        lines += ["", f"Yanıt: {req.note}"]
    if link:
        lines += ["", link]
    return _send([EmailMessage(f"İzin bildiriminiz {verdict} – {req.school}", "\n".join(lines), to=[teacher.email])])
