"""Öğretmenin kendi programı: haftalık ızgara, yaklaşan günler (izin, vekâlet, nöbet) ve telefon takvimi
aboneliği (.ics). Takvim bağlantısı giriş gerektirmez; öğretmene özel gizli anahtarla açılır ve
anahtar yenilenince eski bağlantı çalışmaz.

Takvimde dersler tekrar kuralıyla değil tek tek tarihlerle yazılır (geçen haftadan itibaren WEEKS hafta):
böylece izinli olunan günün dersleri "izinli" görünür, vekâletler ve nöbetler de aynı takvime düşer.
Program değişince telefon takvimi bir sonraki eşitlemede kendiliğinden güncellenir.
"""

import datetime
import secrets
from collections import defaultdict

from django.utils import timezone

from .models import Absence, Duty, Substitution, Timetable

WEEKS = 16
DAY_FULL = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def timetable_for(school):
    """Öğretmenin göreceği program: yayındaki, yoksa en son üretilen."""
    return school.active_timetable or school.timetables.filter(status__in=[Timetable.OK, Timetable.PARTIAL]).first()


def ensure_token(teacher, renew=False):
    if renew or not teacher.calendar_token:
        teacher.calendar_token = secrets.token_urlsafe(24)
        teacher.save(update_fields=["calendar_token"])
    return teacher.calendar_token


def _cards(teacher, timetable):
    if timetable is None:
        return []
    return list(timetable.cards.filter(day__isnull=False, lesson__teachers=teacher).select_related("lesson__subject", "classroom")
                .prefetch_related("lesson__classes"))


def _label(card):
    subject = card.lesson.subject
    classes = ", ".join(c.short or c.name for c in card.lesson.classes.all())
    return subject.short or subject.name, subject.name, classes


def week_grid(teacher, timetable):
    """Satırlar saatler, sütunlar günler: [{"period", "cells": [[{"subject", "name", "classes", "room"}]]}]."""
    school = teacher.school
    periods = list(school.periods.all())
    days = school.days_per_week
    cells = defaultdict(list)
    hours = 0
    for card in _cards(teacher, timetable):
        short, name, classes = _label(card)
        hours += card.length
        for i in range(card.length):
            cells[(card.day, card.period + i)].append({"subject": short, "name": name, "classes": classes,
                                                       "room": card.classroom.name if card.classroom else ""})
    rows = [{"period": p, "span": p.span(), "cells": [cells.get((d, p.index), []) for d in range(days)]} for p in periods]
    return {"days": school.day_names, "rows": rows, "hours": hours}


def _period_times(school):
    return {(p.index, d): p.times(d) for p in school.periods.all() for d in range(school.days_per_week)}


def events(teacher, start, end):
    """[start, end) aralığındaki olaylar: {"date", "start", "end", "title", "kind", "location", "detail", "uid"}."""
    school = teacher.school
    timetable = timetable_for(school)
    times = _period_times(school)
    by_day = defaultdict(list)
    for card in _cards(teacher, timetable):
        by_day[card.day].append(card)
    absences = {a.date: a for a in Absence.objects.filter(teacher=teacher, date__gte=start, date__lt=end)}
    subs = defaultdict(list)
    for sub in (Substitution.objects.filter(substitute=teacher, absence__date__gte=start, absence__date__lt=end)
                .select_related("absence__teacher", "card__lesson__subject").prefetch_related("card__lesson__classes")):
        subs[sub.absence.date].append(sub)
    duties = defaultdict(list)
    for duty in Duty.objects.filter(teacher=teacher).select_related("place"):
        duties[duty.day].append(duty)
    out = []
    date = start
    while date < end:
        weekday = date.weekday()
        if weekday < school.days_per_week:
            absent = absences.get(date)
            for card in sorted(by_day.get(weekday, []), key=lambda c: c.period):
                begin, _ = times.get((card.period, weekday), (None, None))
                _, finish = times.get((card.period + card.length - 1, weekday), (None, None))
                short, name, classes = _label(card)
                out.append({
                    "date": date, "start": begin, "end": finish, "kind": "izin" if absent else "ders",
                    "title": f"{'İzinli: ' if absent else ''}{short} · {classes}",
                    "location": card.classroom.name if card.classroom else "",
                    "detail": f"{name}, {card.period + 1}. saat" + (f" — {absent.reason}" if absent and absent.reason else ""),
                    "uid": f"ders-{card.id}-{date:%Y%m%d}",
                })
            for sub in subs.get(date, []):
                begin, finish = times.get((sub.period, weekday), (None, None))
                short, name, classes = _label(sub.card)
                out.append({
                    "date": date, "start": begin, "end": finish, "kind": "vekalet",
                    "title": f"Vekâlet: {short} · {classes}", "location": sub.card.classroom.name if sub.card.classroom else "",
                    "detail": f"{sub.absence.teacher.full_name} yerine, {sub.period + 1}. saat", "uid": f"vekalet-{sub.id}",
                })
            for duty in duties.get(weekday, []):
                out.append({"date": date, "start": None, "end": None, "kind": "nobet", "title": f"Nöbet: {duty.place.name}",
                            "location": duty.place.name, "detail": "", "uid": f"nobet-{duty.id}-{date:%Y%m%d}"})
        date += datetime.timedelta(days=1)
    out.sort(key=lambda e: (e["date"], e["start"] or datetime.time.min))
    return out


def upcoming(teacher, days=14):
    """Bugünden itibaren olağan dışı günler (izin, vekâlet) ve bugünün planı."""
    today = timezone.localdate()
    items = events(teacher, today, today + datetime.timedelta(days=days))
    special = [e for e in items if e["kind"] in ("izin", "vekalet")]
    return {"today": [e for e in items if e["date"] == today], "special": special}


# --- iCalendar ---------------------------------------------------------------------------------

def _esc(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """RFC 5545: 75 sekizliyi aşan satırlar bölünür (UTF-8 karakter ortasından değil)."""
    data = line.encode()
    if len(data) <= 75:
        return line
    parts, current = [], b""
    for ch in line:
        b = ch.encode()
        if len(current) + len(b) > (75 if not parts else 74):
            parts.append(current.decode())
            current = b""
        current += b
    parts.append(current.decode())
    return "\r\n ".join(parts)


def ics(teacher):
    today = timezone.localdate()
    start = today - datetime.timedelta(days=today.weekday() + 7)  # geçen haftanın pazartesisi
    items = events(teacher, start, start + datetime.timedelta(weeks=WEEKS + 1))
    stamp = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Ders Programi//TR", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_esc(f'Ders programı – {teacher.full_name}')}", "X-WR-TIMEZONE:Europe/Istanbul",
             "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
             # Türkiye 2016'dan beri yaz saati uygulamıyor: sabit +03
             "BEGIN:VTIMEZONE", "TZID:Europe/Istanbul", "BEGIN:STANDARD", "DTSTART:19700101T000000",
             "TZOFFSETFROM:+0300", "TZOFFSETTO:+0300", "TZNAME:+03", "END:STANDARD", "END:VTIMEZONE"]
    for e in items:
        lines += ["BEGIN:VEVENT", f"UID:{e['uid']}@ders-programi", f"DTSTAMP:{stamp}"]
        if e["start"] and e["end"]:
            lines += [f"DTSTART;TZID=Europe/Istanbul:{e['date']:%Y%m%d}T{e['start']:%H%M%S}",
                      f"DTEND;TZID=Europe/Istanbul:{e['date']:%Y%m%d}T{e['end']:%H%M%S}"]
        else:  # saati bilinmeyen ders ya da nöbet: tüm gün
            lines += [f"DTSTART;VALUE=DATE:{e['date']:%Y%m%d}",
                      f"DTEND;VALUE=DATE:{e['date'] + datetime.timedelta(days=1):%Y%m%d}", "TRANSP:TRANSPARENT"]
        lines.append(f"SUMMARY:{_esc(e['title'])}")
        if e["location"]:
            lines.append(f"LOCATION:{_esc(e['location'])}")
        if e["detail"]:
            lines.append(f"DESCRIPTION:{_esc(e['detail'])}")
        if e["kind"] == "izin":
            lines.append("STATUS:CANCELLED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
