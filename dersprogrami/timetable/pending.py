"""Bekleyenler: yerleşmemiş her kartın neden yerleşmediği ve ne yapılabileceği.

Her bekleyen kart için kartın konabileceği tüm başlangıç saatleri üç gruba ayrılır:
- müsaitlik yüzünden kapalı (hangi öğretmen/sınıf/ders/okul kapatıyor),
- açık ama dolu (o saatte kiminle çakışıyor: öğretmen, sınıf, derslik),
- boş (kart oraya hemen konabilir).
En büyük engel kartın "neden"i olur; öneri ona göre verilir.
"""

from collections import Counter

from .editing import BLOCKED, CONFLICT, SHIFT, Board
from .refs import DAY_SHORT

KINDS = {
    "free": "Boş görünen saat var",
    "conflict": "Uygun saatler dolu",
    "availability": "Müsaitlik kapatıyor",
    "length": "Kart günlere sığmıyor",
}


def _where(day, period):
    return f"{DAY_SHORT[day]} {period + 1}"


def analyze(timetable):
    board = Board(timetable)
    problem = board.problem
    entity_labels = problem.labels.get("entity", {})
    db = board.db_cards
    lessons = {c.lesson_id: c for c in timetable.cards.select_related("lesson__subject").prefetch_related(
        "lesson__classes", "lesson__teachers") if c.day is None}
    rows = []
    for pc in problem.cards:
        card = db.get(pc.card_id)
        if card is None or card.is_placed:
            continue
        lesson = lessons[pc.lesson_id].lesson if pc.lesson_id in lessons else card.lesson
        possible = problem.days * max(0, problem.periods - pc.length + 1)
        blocked_by = Counter(entity_labels.get(e, str(e)) for culprits in pc.blocked.values() for e in culprits)
        free, conflicts, busy = [], Counter(), 0
        for day, period in sorted(pc.starts):
            info = board.evaluate(pc.card_id, day, period)
            if info["status"] == BLOCKED:
                continue
            if info["status"] in (CONFLICT, SHIFT):
                busy += 1
                for c in info["conflicts"]:
                    for resource in c["resources"]:
                        conflicts[resource] += 1
            else:
                free.append({"day": day, "period": period, "label": _where(day, period), "warn": info["reasons"]})
        if free:
            kind = "free"
            text = (f"{len(free)} saat boş görünüyor: {', '.join(f['label'] for f in free[:4])}{'…' if len(free) > 4 else ''}. "
                    "Kart ilişkisi kuralları yerleştirirken denetlenir.")
        elif not pc.starts:
            kind = "availability" if pc.blocked else "length"
            text = ("Tüm saatler müsaitlik yüzünden kapalı." if pc.blocked
                    else f"{pc.length} saatlik blok, günün ders saatlerine ya da uzun teneffüs sınırlarına sığmıyor.")
        else:
            kind = "conflict"
            top = conflicts.most_common(1)[0] if conflicts else ("", 0)
            text = f"Açık {len(pc.starts)} saatin hepsi dolu; en çok {top[0]} ile çakışıyor ({top[1]} saatte)."
        rows.append({
            "id": pc.card_id,
            "subject": lesson.subject.name,
            "short": lesson.subject.short or lesson.subject.name,
            "classes": ", ".join(c.short or c.name for c in lesson.classes.all()),
            "teachers": ", ".join(t.full_name for t in lesson.teachers.all()),
            "length": pc.length,
            "possible": possible,
            "open": len(pc.starts),
            "blocked": len(pc.blocked),
            "blocked_by": blocked_by.most_common(4),
            "busy": busy,
            "conflicts": conflicts.most_common(4),
            "free": free[:8],
            "kind": kind,
            "kind_label": KINDS[kind],
            "text": text,
        })
    order = {"free": 0, "conflict": 1, "availability": 2, "length": 3}
    rows.sort(key=lambda r: (order[r["kind"]], r["classes"], r["subject"]))
    summary = {kind: sum(1 for r in rows if r["kind"] == kind) for kind in KINDS}
    hours = sum(r["length"] for r in rows)
    # Okul genelinde en çok engel olanlar
    top_conflicts = Counter()
    top_blocks = Counter()
    for r in rows:
        if r["conflicts"]:
            top_conflicts[r["conflicts"][0][0]] += 1
        for label, _ in r["blocked_by"][:1]:
            top_blocks[label] += 1
    kinds = [(k, label, summary[k]) for k, label in KINDS.items() if k != "length" or summary[k]]
    return {"rows": rows, "summary": summary, "kinds": kinds, "hours": hours, "labels": KINDS,
            "top_conflicts": top_conflicts.most_common(6), "top_blocks": top_blocks.most_common(6)}


def try_place(timetable, card_id, limit=15):
    """Bekleyen kartı, tüm kurallarla (kart ilişkileri dahil) denetlenen ilk boş saate koyar.
    Dönüş: {"ok", "message"}; olmazsa engelleyen ilk kural iletide yazar."""
    from . import editing
    from .services import placements_of
    from .solver.cpsat import Placement
    from .solver.validate import validate

    board = Board(timetable)
    problem = board.problem
    pc = board.by_id.get(card_id)
    card = board.db_cards.get(card_id)
    if pc is None or card is None:
        return {"ok": False, "message": "Kart bulunamadı."}
    if card.is_placed:
        return {"ok": False, "message": "Kart zaten yerleşmiş."}
    base = placements_of(problem, timetable)
    before = {v.message for v in validate(problem, base)[0] if v.level == "hard"}
    first_reason, tried = "", 0
    for day, period in sorted(pc.starts):
        info = board.evaluate(card_id, day, period)
        if info["status"] in (BLOCKED, CONFLICT, SHIFT):
            continue
        tried += 1
        rooms = info.get("rooms") or []
        trial = dict(base)
        trial[pc.key] = Placement(day, period, rooms[0] if rooms else None, tuple(rooms[1:]))
        new = [v for v in validate(problem, trial)[0] if v.level == "hard" and v.message not in before]
        if not new:
            result = editing.move_card(card, day, period, mode="ask")
            if result.get("ok"):
                return {"ok": True, "message": f"{problem.label('lesson', pc.lesson_id)}: {_where(day, period)} saatine yerleştirildi."}
        elif not first_reason:
            first_reason = new[0].message
        if tried >= limit:
            break
    if not tried:
        return {"ok": False, "message": "Boş uygun saat yok; “Yer aç” ile diğer dersleri oynatarak deneyin."}
    return {"ok": False, "message": f"Boş görünen saatlerin hepsi bir kurala takılıyor. Örnek: {first_reason} “Yer aç” ile deneyin."}
