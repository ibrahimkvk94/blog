"""Sürüm karşılaştırma ve değişiklik bildirimi: bir programın başka bir programa (ör. yayındaki) ya da kendi kayıtlı
bir sürümüne göre değişen dersleri, öğretmen başına "eski yer → yeni yer" olarak listeler; yazdırılır ve
öğretmenlere e-postayla gönderilir.

Kartlar sürümler arasında farklı kimlik taşıyabilir: ders bazında eşleştirilir (aynı yer → değişmemiş; aynı saat,
farklı derslik → derslik değişti; kalanlar sırayla eşleşir; artanlar yerleşti / çıkarıldı). Sürümler derslerin öğretmen
atamalarını da sakladığından öğretmeni değişen dersler (ör. öğretmen havuzu) hem eski hem yeni öğretmene bildirilir.
"""

from collections import defaultdict

from .models import Timetable
from .refs import DAY_SHORT
from .textsort import natural_key
from .versions import current_state, current_teachers, teacher_diff


def sources(timetable):
    """Karşılaştırılabilecekler: okulun diğer programları ve bu programın kayıtlı sürümleri."""
    school = timetable.school
    out = []
    for tt in school.timetables.exclude(pk=timetable.pk).exclude(status__in=[Timetable.FAILED, Timetable.RUNNING]):
        out.append({"key": f"tt-{tt.pk}", "label": f"Program: {tt.name}" + (" (yayında)" if tt.pk == school.active_timetable_id else "")})
    for v in timetable.versions.order_by("-number")[:40]:
        out.append({"key": f"v-{v.pk}", "label": f"Sürüm #{v.number} · {v.created_at:%d.%m %H:%M}" + (f" · {v.note}" if v.note else "")})
    return out


def default_source(timetable):
    school = timetable.school
    if school.active_timetable_id and school.active_timetable_id != timetable.pk:
        return f"tt-{school.active_timetable_id}"
    state = current_state(timetable)
    for v in timetable.versions.order_by("-number")[:40]:
        if v.cards != state:
            return f"v-{v.pk}"
    return ""


class Slots(defaultdict):
    """{ders: [yer]}; teachers: o andaki öğretmen atamaları (bilinmiyorsa boş)."""

    def __init__(self, teachers=None):
        super().__init__(list)
        self.teachers = teachers or {}


def _slot(day, period, length, rooms):
    return (day, period, length, tuple(sorted(r for r in rooms if r)))


def _slots_of_timetable(tt):
    last = tt.versions.order_by("-number").first()
    slots = Slots(last.teachers if last else None)
    for card in tt.cards.all():
        slots[card.lesson_id].append(_slot(card.day, card.period, card.length, card.room_ids))
    return slots


def _slots_of_version(timetable, version):
    cards = {c.id: c for c in timetable.cards.all()}
    slots = Slots(version.teachers)
    for card_id, day, period, room, extra, _locked in version.cards:
        card = cards.get(card_id)
        if card is not None:
            slots[card.lesson_id].append(_slot(day, period, card.length, [room] + list(extra or [])))
    return slots


def resolve_source(timetable, key):
    """Dönüş: (etiket, {ders: [yer]}) ya da (None, None)."""
    kind, _, pk = (key or "").partition("-")
    if not pk.isdigit():
        return None, None
    if kind == "tt":
        other = timetable.school.timetables.filter(pk=pk).first()
        return (other.name, _slots_of_timetable(other)) if other else (None, None)
    if kind == "v":
        version = timetable.versions.filter(pk=pk).first()
        return (f"Sürüm #{version.number}", _slots_of_version(timetable, version)) if version else (None, None)
    return None, None


def compare(timetable, before):
    """Değişiklikler: [{"lesson_id", "before", "after", "kind"}]; kind: moved | room | placed | removed."""
    after = _slots_of_timetable(timetable)
    rows = []
    for lesson_id in set(after) | set(before):
        a, b = list(after.get(lesson_id, [])), list(before.get(lesson_id, []))
        for s in list(a):  # aynı yer ve derslik
            if s in b:
                a.remove(s)
                b.remove(s)
        for s in list(a):  # aynı saat, farklı derslik
            match = next((x for x in b if x[:3] == s[:3]), None)
            if match is not None:
                a.remove(s)
                b.remove(match)
                if s[0] is not None:
                    rows.append({"lesson_id": lesson_id, "before": match, "after": s, "kind": "room"})
        key = lambda s: (s[0] is None, s[0] or 0, s[1] or 0)  # noqa: E731
        a.sort(key=key)
        b.sort(key=key)
        for i in range(max(len(a), len(b))):
            new, old = (a[i] if i < len(a) else None), (b[i] if i < len(b) else None)
            new_placed = new is not None and new[0] is not None
            old_placed = old is not None and old[0] is not None
            if not new_placed and not old_placed:
                continue
            kind = "moved" if new_placed and old_placed else "placed" if new_placed else "removed"
            rows.append({"lesson_id": lesson_id, "before": old if old_placed else None, "after": new if new_placed else None, "kind": kind})
    old_teachers = getattr(before, "teachers", None)
    now = current_teachers(timetable) if old_teachers else {}
    for key in teacher_diff(old_teachers, now):
        lesson_id = int(key)
        placed = sorted((s for s in after.get(lesson_id, []) if s[0] is not None), key=lambda s: (s[0], s[1]))
        rows.append({"lesson_id": lesson_id, "kind": "teacher", "before": None, "after": placed[0] if placed else None,
                     "old_teachers": old_teachers[key], "new_teachers": now[key]})
    return rows


def describe(timetable, rows):
    """Öğretmen başına gruplanmış okunur satırlar ve özet."""
    school = timetable.school
    periods = {p.index: p for p in school.periods.all()}
    rooms = {r.id: r.name for r in school.classrooms.all()}
    from .models import Lesson

    lessons = {l.id: l for l in Lesson.objects.filter(pk__in={r["lesson_id"] for r in rows}).select_related("subject")
               .prefetch_related("classes", "teachers")}

    def where(slot):
        if slot is None:
            return "—"
        day, period, length, room_ids = slot
        end = period + length - 1
        first, last = periods.get(period), periods.get(end)
        start_t = first.times(day)[0] if first else None
        end_t = last.times(day)[1] if last else None
        text = f"{DAY_SHORT[day]} {period + 1}" + (f"–{end + 1}" if length > 1 else "") + ". saat"
        if start_t and end_t:
            text += f" ({start_t:%H:%M}–{end_t:%H:%M})"
        if room_ids:
            text += " · " + ", ".join(rooms.get(r, "?") for r in room_ids)
        return text

    from .models import Teacher

    involved = {t for r in rows if r["kind"] == "teacher" for t in r["old_teachers"] + r["new_teachers"]}
    people = {t.id: t for t in Teacher.objects.filter(pk__in=involved)}

    def who(ids):
        return ", ".join(people[t].full_name for t in ids if t in people) or "öğretmensiz"

    by_teacher = defaultdict(list)
    names = {}
    for r in rows:
        lesson = lessons.get(r["lesson_id"])
        if lesson is None:
            continue
        slot = r["after"] or r["before"]
        item = {
            "subject": lesson.subject.short or lesson.subject.name, "subject_name": lesson.subject.name,
            "classes": ", ".join(sorted((c.short or c.name for c in lesson.classes.all()), key=natural_key)),
            "before": where(r["before"]), "after": where(r["after"]), "kind": r["kind"],
            "sort": slot[:2] if slot else (None, None),
        }
        if r["kind"] == "teacher":
            item["before"] = "Öğretmen: " + who(r["old_teachers"])
            item["after"] = "Öğretmen: " + who(r["new_teachers"]) + (f" · {where(r['after'])}" if r["after"] else "")
            teachers = [people[t] for t in dict.fromkeys(r["old_teachers"] + r["new_teachers"]) if t in people] or [None]
        else:
            teachers = list(lesson.teachers.all()) or [None]
        for t in teachers:
            key = t.id if t else 0
            names[key] = t
            by_teacher[key].append(item)
    groups = []
    for key, items in by_teacher.items():
        t = names[key]
        items.sort(key=lambda i: (i["sort"][0] if i["sort"][0] is not None else 9, i["sort"][1] or 0))
        groups.append({"teacher": t, "name": t.full_name if t else "Öğretmensiz dersler", "email": t.email if t else "",
                       "items": items, "moved": sum(1 for i in items if i["kind"] != "room")})
    groups.sort(key=lambda g: (g["teacher"] is None, natural_key(g["name"])))
    return {"groups": groups, "lessons": len({r["lesson_id"] for r in rows}), "changes": len(rows),
            "teachers": sum(1 for g in groups if g["teacher"] is not None)}


def emails(school, groups, teacher_ids, note, link=""):
    """Seçili öğretmenlere kendi değişiklik listeleri. Dönüş: (gönderilen, hatalar)."""
    from django.core.mail import EmailMessage

    from . import notify

    if not notify.enabled():
        return 0, ["E-posta sunucusu ayarlı değil."]
    messages = []
    for g in groups:
        t = g["teacher"]
        if t is None or t.id not in teacher_ids or not t.email:
            continue
        lines = [f"Sayın {t.full_name},", "", f"{school} ders programınızda aşağıdaki değişiklikler var:", ""]
        for i in g["items"]:
            lines.append(f"• {i['subject_name']} ({i['classes']}): {i['before']} → {i['after']}")
        if note:
            lines += ["", note]
        if link:
            lines += ["", link]
        messages.append(EmailMessage(f"Ders programınız değişti – {school}", "\n".join(lines), to=[t.email]))
    return notify._send(messages)
