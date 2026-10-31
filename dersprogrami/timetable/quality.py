"""Kalite karnesi: her öğretmen ve sınıf için programın ne kadar "rahat" olduğunu ölçer.

Ölçütler (haftalık): boşluk saati, okula gelinen gün, yalnızca tek ders için gelinen gün, gereğinden fazla
gün, geç başlanan gün (sınıflarda), yerleşmemiş ders saati ve kişiyi ilgilendiren ihlaller. Ceza puanı bu
ölçütlerin ağırlıklı toplamıdır; büyük puan daha kötü programdır. "İyileştir" (improve.py) aynı puanı azaltır.
"""

import math
import re
from collections import defaultdict

from .grid import KINDS
from .services import verify_timetable
from .textsort import natural_key

WEIGHTS = {"gaps": 2, "single_days": 3, "extra_days": 1, "late_days": 1, "unplaced": 4, "hard": 10, "soft": 2}
LATE_HOUR = 16  # bu saatte ya da sonra başlayan ders saati "geç saat"
LEVELS = ((3, "iyi", "İyi"), (10, "orta", "Orta"), (None, "kotu", "Kötü"))


def _gaps(periods):
    return max(periods) - min(periods) + 1 - len(periods) if periods else 0


def _level(score):
    for limit, key, label in LEVELS:
        if limit is None or score <= limit:
            return key, label


def _mentions(labels):
    """Ad, ihlal metninde tam sözcük olarak geçiyor mu ("1.KISIM", "11.KISIM"nin içinde sayılmaz)."""
    pattern = re.compile("|".join(r"(?<![\w.])" + re.escape(x) + r"(?!\w)" for x in labels if x))
    return lambda text: bool(pattern.search(text))


def late_periods(school):
    """Geç saat sayılan ders saatleri (0'dan sıra): saatleri girilmişse 16.00 ve sonrası başlayanlar,
    girilmemişse günün son iki saati (günde 4 saat ya da daha azsa son saat)."""
    periods = list(school.periods.order_by("index"))
    if any(p.start_time for p in periods):
        return frozenset(p.index for p in periods if p.start_time and p.start_time.hour >= LATE_HOUR)
    tail = 2 if len(periods) > 4 else 1
    return frozenset(p.index for p in periods[-tail:])


def _row(name, sub, by_day, unplaced, hard, soft, periods_per_day, late=False, late_set=frozenset()):
    """by_day: gün → dolu saatler kümesi; late_set: geç saat sayılan saatler (yalnızca bilgi, puana girmez)."""
    hours = sum(len(p) for p in by_day.values())
    days = [d for d, p in by_day.items() if p]
    gaps = sum(_gaps(by_day[d]) for d in days)
    max_gaps = max((_gaps(by_day[d]) for d in days), default=0)
    single = sum(1 for d in days if len(by_day[d]) == 1)
    # Gereğinden fazla gün yalnızca öğretmenler için anlamlı (sınıf her gün okuldadır).
    extra = max(0, len(days) - math.ceil(hours / periods_per_day)) if hours and not late else 0
    late_days = sum(1 for d in days if min(by_day[d]) > 0) if late else 0
    parts = {"gaps": gaps, "single_days": single, "extra_days": extra, "late_days": late_days,
             "unplaced": unplaced, "hard": hard, "soft": soft}
    score = sum(WEIGHTS[k] * v for k, v in parts.items())
    # İyileştirmenin (ders oynatarak) düzeltebileceği kısım: boşluk ve gün sorunları
    fixable = sum(WEIGHTS[k] * parts[k] for k in ("gaps", "single_days", "extra_days", "late_days"))
    level, level_label = _level(score)
    # Puana girmeyen, karşılaştırma için bilgi: bir günde en çok ders saati ve geç saatlerdeki ders saati
    max_day = max((len(by_day[d]) for d in days), default=0)
    late_hours = sum(len(by_day[d] & late_set) for d in days)
    return {"name": name, "sub": sub, "hours": hours, "days": len(days), "max_gaps": max_gaps, **parts,
            "max_day": max_day, "late_hours": late_hours,
            "score": score, "fixable": fixable, "level": level, "level_label": level_label}


def violations_of(timetable):
    """Kalite karnesinin saydığı ihlaller: yerleşmeyenler hariç (onlar saat olarak ayrıca sayılır)."""
    violations, _ = verify_timetable(timetable)
    return [v for v in violations if v.code != "unplaced"]


def report(timetable, kind="ogretmen", violations=None):
    """Dönüş: {"rows": [...], "summary": {...}}; satırlar en kötüden iyiye.

    violations: violations_of(timetable) önceden hesaplandıysa verilir (aynı programın iki türü tek doğrulamayla)."""
    if kind not in ("ogretmen", "sinif"):
        kind = "ogretmen"
    school = timetable.school
    periods_per_day = max(1, school.periods.count())
    late_set = late_periods(school)
    if violations is None:
        violations = violations_of(timetable)
    busy = defaultdict(lambda: defaultdict(set))
    unplaced = defaultdict(int)
    cards = timetable.cards.select_related("lesson").prefetch_related("lesson__teachers", "lesson__classes")
    for card in cards:
        owners = card.lesson.teachers.all() if kind == "ogretmen" else card.lesson.classes.all()
        for owner in owners:
            if card.day is None:
                unplaced[owner.id] += card.length
            else:
                busy[owner.id][card.day].update(range(card.period, card.period + card.length))
    objects = list(getattr(school, KINDS[kind]).all())
    rows = []
    for obj in objects:
        name = obj.full_name if kind == "ogretmen" else obj.name
        label = name if kind == "ogretmen" else (obj.short or obj.name)
        mentions = _mentions({label, name})
        mine = [v for v in violations if mentions(v.message)]
        sub = " · ".join(filter(None, [obj.department, obj.title])) if kind == "ogretmen" else (obj.short if obj.short != obj.name else "")
        row = _row(name, sub, busy[obj.id], unplaced[obj.id], sum(v.level == "hard" for v in mine),
                   sum(v.level != "hard" for v in mine), periods_per_day, late=kind == "sinif", late_set=late_set)
        row.update(id=obj.id, search=label, issues=[v.message for v in mine][:6])
        rows.append(row)
    rows = [r for r in rows if r["hours"] or r["unplaced"]]
    rows.sort(key=lambda r: (-r["score"], natural_key(r["name"])))
    summary = {
        "count": len(rows),
        "levels": {key: sum(1 for r in rows if r["level"] == key) for _, key, _ in LEVELS},
        "gaps": sum(r["gaps"] for r in rows),
        "single_days": sum(r["single_days"] for r in rows),
        "extra_days": sum(r["extra_days"] for r in rows),
        "late_days": sum(r["late_days"] for r in rows),
        "unplaced": sum(r["unplaced"] for r in rows),
        "score": sum(r["score"] for r in rows),
        "with_gaps": sum(1 for r in rows if r["gaps"]),
    }
    return {"kind": kind, "rows": rows, "summary": summary}
