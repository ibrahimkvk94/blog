"""Derslik doluluğu: gün × saat başına dolu derslik oranı ve derslik başına haftalık kullanım.

Bir derslik bir hücrede "kullanılabilir" sayılır: okul geneli ve dersliğin kendi müsaitliği o hücreyi
kapatmıyorsa. Doluluk = o hücrede dersi olan kullanılabilir derslik / kullanılabilir derslik.
"""

from collections import defaultdict

from .models import Availability
from .textsort import natural_key


def _level(pct):
    return 0 if pct is None else min(5, int(pct // 20) + (1 if pct > 0 else 0))  # 0 boş … 5 dolu


def report(timetable):
    school = timetable.school
    days, periods = school.day_names, list(school.periods.all())
    D, P = len(days), len(periods)
    rooms = sorted(school.classrooms.select_related("building"), key=lambda r: natural_key(r.name))
    school_closed = set(Availability.objects.filter(school=school, state=Availability.NO,
                                                    **{f"{f}__isnull": True for f in Availability.TARGET_FIELDS})
                        .values_list("day", "period"))
    room_closed = defaultdict(set)
    for room_id, d, p in Availability.objects.filter(school=school, classroom__isnull=False, state=Availability.NO).values_list("classroom_id", "day", "period"):
        room_closed[room_id].add((d, p))
    busy = defaultdict(lambda: defaultdict(list))  # derslik → hücre → dersler
    for card in timetable.cards.filter(day__isnull=False).select_related("lesson__subject").prefetch_related("lesson__classes"):
        label = f"{card.lesson.subject.short or card.lesson.subject.name} ({', '.join(c.short or c.name for c in card.lesson.classes.all())})"
        for room_id in card.room_ids:
            for i in range(card.length):
                busy[room_id][(card.day, card.period + i)].append(label)

    def available(room, cell):
        return cell not in school_closed and cell not in room_closed[room.id]

    room_rows = []
    for room in rooms:
        cells = [(d, p) for d in range(D) for p in range(P)]
        open_cells = [c for c in cells if available(room, c)]
        used = [c for c in open_cells if busy[room.id].get(c)]
        pct = round(100 * len(used) / len(open_cells)) if open_cells else None
        strip = [[("closed" if not available(room, (d, p)) else "busy" if busy[room.id].get((d, p)) else "free") for p in range(P)] for d in range(D)]
        room_rows.append({"room": room, "building": room.building.name if room.building else "", "used": len(used),
                          "open": len(open_cells), "pct": pct, "level": _level(pct), "strip": strip})
    grid = []
    for p_obj in periods:
        row = []
        for d in range(D):
            cell = (d, p_obj.index)
            open_rooms = [r for r in rooms if available(r, cell)]
            used = [r for r in open_rooms if busy[r.id].get(cell)]
            pct = round(100 * len(used) / len(open_rooms)) if open_rooms else None
            row.append({"day": d, "period": p_obj.index, "pct": pct, "level": _level(pct), "used": len(used), "open": len(open_rooms),
                        "free": [r.name for r in open_rooms if not busy[r.id].get(cell)],
                        "busy": [f"{r.name}: {', '.join(busy[r.id][cell])}" for r in used]})
        grid.append({"period": p_obj, "span": p_obj.span(), "cells": row})
    all_cells = [c for row in grid for c in row["cells"] if c["pct"] is not None]
    peak = max(all_cells, key=lambda c: c["pct"], default=None)
    used_rows = [r for r in room_rows if r["pct"] is not None]
    summary = {
        "rooms": len(rooms),
        "average": round(sum(r["pct"] for r in used_rows) / len(used_rows)) if used_rows else 0,
        "peak": {"label": f"{days[peak['day']]} {peak['period'] + 1}. saat", "pct": peak["pct"], "used": peak["used"], "open": peak["open"]} if peak else None,
        "idle": sum(1 for r in used_rows if r["pct"] < 20),
        "full": sum(1 for r in used_rows if r["pct"] >= 80),
        "unused": sum(1 for r in used_rows if r["used"] == 0),
    }
    return {"days": days, "grid": grid, "rooms": room_rows, "summary": summary,
            "buildings": any(r["building"] for r in room_rows)}
