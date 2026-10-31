"""Program karşılaştırma karnesi: aynı okulun iki programını (ör. aSc'den içe aktarılan ve burada üretilen)
aynı ölçütlerle yan yana koyar; hangisinin, nerede daha iyi olduğunu söyler.

Kişi başı ölçütler kalite karnesinden (quality.report) gelir; burada yalnızca iki tarafı eşleştirip özetleriz.
Bütün ölçütlerde küçük değer daha iyidir.
"""

import io

from .models import Timetable
from .quality import _row, late_periods, report, violations_of
from .textsort import natural_key

DEFAULT_THRESHOLD = 4

# (anahtar, ad, açıklama); açıklamadaki {n}: "çok boşluklu öğretmen" eşiği
METRICS = [
    ("hard", "Kesin ihlal", "çakışma, müsait olmayan saat, kural ihlali"),
    ("unplaced", "Yerleşmemiş kart", "programa giremeyen kartlar"),
    ("soft", "Tercih ihlali", "yumuşak kurallar"),
    ("score", "Kalite puanı", "öğretmen + sınıf ceza puanı (kalite karnesi)"),
    ("teacher_gaps", "Öğretmen boşluk saati", "haftalık toplam"),
    ("gappy_teachers", "Çok boşluklu öğretmen", "haftada {n} saatten fazla boşluğu olan"),
    ("single_days", "Tek saatlik gün", "öğretmenin yalnızca 1 ders için geldiği günler"),
    ("avg_days", "Ortalama gün", "öğretmen başına okula gelinen gün"),
    ("max_days", "En çok gün", "bir öğretmenin geldiği en çok gün"),
    ("max_day", "Günde en çok ders", "bir öğretmenin bir günde girdiği en çok ders saati"),
    ("late_hours", "Geç saat dersi", "geç saatlere düşen ders saati"),
    ("class_gaps", "Sınıf boşluk saati", "haftalık toplam"),
    ("late_days", "Sınıf geç başlama", "günün ilk saati boş olan sınıf-gün"),
]

# Kişi/sınıf tablolarında karşılaştırılan sütunlar (anahtar, kısa başlık)
TEACHER_COLUMNS = [("score", "Puan"), ("hours", "Saat"), ("days", "Gün"), ("gaps", "Boşluk"), ("single_days", "Tek saatlik gün"),
                   ("max_day", "Günde en çok"), ("late_hours", "Geç saat"), ("unplaced", "Bekleyen"), ("hard", "İhlal")]
CLASS_COLUMNS = [("score", "Puan"), ("hours", "Saat"), ("gaps", "Boşluk"), ("late_days", "Geç başlama"),
                 ("max_day", "Günde en çok"), ("late_hours", "Geç saat"), ("unplaced", "Bekleyen"), ("hard", "İhlal")]


def _side(timetable, threshold):
    """Bir programın özet ölçütleri ve kişi/sınıf satırları."""
    violations = violations_of(timetable)
    teachers = report(timetable, "ogretmen", violations)
    classes = report(timetable, "sinif", violations)
    late_set = late_periods(timetable.school)
    unplaced = late_hours = 0
    for day, period, length in timetable.cards.values_list("day", "period", "length"):
        if day is None:
            unplaced += 1
        else:
            late_hours += len(set(range(period, period + length)) & late_set)
    taught = [r for r in teachers["rows"] if r["hours"]]
    metrics = {
        "hard": sum(1 for v in violations if v.level == "hard"),
        "unplaced": unplaced,
        "soft": sum(1 for v in violations if v.level != "hard"),
        "score": teachers["summary"]["score"] + classes["summary"]["score"],
        "teacher_gaps": teachers["summary"]["gaps"],
        "gappy_teachers": sum(1 for r in taught if r["gaps"] > threshold),
        "single_days": teachers["summary"]["single_days"],
        "avg_days": round(sum(r["days"] for r in taught) / len(taught), 2) if taught else 0,
        "max_days": max((r["days"] for r in taught), default=0),
        "max_day": max((r["max_day"] for r in taught), default=0),
        "late_hours": late_hours,
        "class_gaps": classes["summary"]["gaps"],
        "late_days": classes["summary"]["late_days"],
    }
    return {"timetable": timetable, "metrics": metrics, "ogretmen": teachers["rows"], "sinif": classes["rows"]}


def _better(a, b):
    return "a" if a < b else "b" if b < a else None


def _pair(rows_a, rows_b, columns):
    """İki tarafın satırlarını kişi/sınıf kimliğiyle eşleştirir; bir tarafta dersi yoksa sıfır satır."""
    by_a, by_b = {r["id"]: r for r in rows_a}, {r["id"]: r for r in rows_b}
    pairs = []
    for pk in by_a.keys() | by_b.keys():
        ref = by_a.get(pk) or by_b[pk]
        empty = _row(ref["name"], ref["sub"], {}, 0, 0, 0, 1)
        a, b = by_a.get(pk, empty), by_b.get(pk, empty)
        delta = {key: a[key] - b[key] for key, _ in columns}
        status = "kotu" if delta["score"] > 0 else "iyi" if delta["score"] < 0 else "ayni"
        pairs.append({"id": pk, "name": ref["name"], "sub": ref["sub"], "search": ref["search"], "a": a, "b": b,
                      "cells": [{"key": key, "a": a[key], "b": b[key], "d": delta[key]} for key, _ in columns],
                      "delta": delta, "status": status, "changed": any(delta.values())})
    # En çok kötüleşen üstte, sonra en çok iyileşen, eşitler adına göre
    pairs.sort(key=lambda p: (-p["delta"]["score"], natural_key(p["name"])))
    return pairs


def ordinal_locative(n):
    """Sayının bulunma hâli iyelik eki: 5 → "5'inde", 7 → "7'sinde", 10 → "10'unda"."""
    ones = {1: "inde", 2: "sinde", 3: "ünde", 4: "ünde", 5: "inde", 6: "sında", 7: "sinde", 8: "inde", 9: "unda"}
    tens = {1: "unda", 2: "sinde", 3: "unda", 4: "ında", 5: "sinde", 6: "ında", 7: "inde", 8: "inde", 9: "ında"}
    if n % 10:
        suffix = ones[n % 10]
    elif n % 100:
        suffix = tens[(n % 100) // 10]
    else:
        suffix = "ında" if n == 0 else "ünde"
    return f"{n}'{suffix}"


def compare(timetable_a, timetable_b, threshold=DEFAULT_THRESHOLD):
    """A ("bu program") ile B'yi karşılaştırır. Dönüş: özet satırları, başlık cümlesi ve kişi/sınıf eşleşmeleri."""
    side_a, side_b = _side(timetable_a, threshold), _side(timetable_b, threshold)
    summary = []
    for key, label, hint in METRICS:
        a, b = side_a["metrics"][key], side_b["metrics"][key]
        summary.append({"key": key, "label": label, "hint": hint.format(n=threshold), "a": a, "b": b,
                        "delta": round(a - b, 2), "better": _better(a, b)})
    wins = sum(1 for m in summary if m["better"] == "a")
    losses = sum(1 for m in summary if m["better"] == "b")
    ties = len(summary) - wins - losses
    if wins > losses:
        verdict = "a"
    elif losses > wins:
        verdict = "b"
    else:
        verdict = None
    headline = f"Bu program {len(summary)} ölçütün {ordinal_locative(wins)} daha iyi"
    detail = f"{losses} ölçütte daha kötü, {ties} ölçütte eşit."
    # Kesin ihlal ve yerleşmeyen kart programın kullanılabilirliğini belirler: en önce onlara bakılır.
    critical = next((m for m in summary[:2] if m["better"]), None)
    teachers = _pair(side_a["ogretmen"], side_b["ogretmen"], TEACHER_COLUMNS)
    classes = _pair(side_a["sinif"], side_b["sinif"], CLASS_COLUMNS)

    def counts(pairs):
        return {s: sum(1 for p in pairs if p["status"] == s) for s in ("iyi", "kotu", "ayni")}

    return {
        "a": side_a["timetable"], "b": side_b["timetable"], "threshold": threshold,
        "summary": summary, "wins": wins, "losses": losses, "ties": ties, "verdict": verdict,
        "headline": headline, "detail": detail, "critical": critical,
        "ogretmen": teachers, "sinif": classes, "teacher_counts": counts(teachers), "class_counts": counts(classes),
        "teacher_columns": TEACHER_COLUMNS, "class_columns": CLASS_COLUMNS,
    }


def default_other(timetable):
    """İkinci program için öneri: bu program aSc'den gelmediyse aSc'den içe aktarılan, yoksa en son diğer program."""
    from .input_diff import ASC_TIMETABLE

    others = candidates(timetable)
    if timetable.name != ASC_TIMETABLE:
        asc = next((t for t in others if t.name == ASC_TIMETABLE), None)
        if asc is not None:
            return asc
    return others[0] if others else None


def candidates(timetable):
    """Karşılaştırılabilecek programlar: aynı okulun ızgarası olan diğer programları, yeniden eskiye."""
    return list(timetable.school.timetables.exclude(pk=timetable.pk)
                .filter(status__in=[Timetable.OK, Timetable.PARTIAL, Timetable.DRAFT]).order_by("-pk"))


def workbook(data):
    """Karşılaştırmanın Excel dosyası: Özet, Öğretmenler, Sınıflar sayfaları."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    better = PatternFill("solid", fgColor="DCFCE7")
    worse = PatternFill("solid", fgColor="FEE2E2")
    bold = Font(bold=True)
    name_a, name_b = data["a"].name, data["b"].name
    wb = Workbook()
    ws = wb.active
    ws.title = "Özet"
    ws.append([f"{data['headline']} ({data['detail']})"])
    ws["A1"].font = bold
    ws.append([])
    ws.append(["Ölçüt", f"Bu program: {name_a}", f"Karşılaştırılan: {name_b}", "Fark", "Açıklama"])
    for cell in ws[3]:
        cell.font = bold
    for m in data["summary"]:
        ws.append([m["label"], m["a"], m["b"], m["delta"], m["hint"]])
        if m["better"]:
            ws.cell(ws.max_row, 2 if m["better"] == "a" else 3).fill = better
            ws.cell(ws.max_row, 3 if m["better"] == "a" else 2).fill = worse
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = ws.column_dimensions["C"].width = 30
    ws.column_dimensions["E"].width = 50
    for title, key, columns, label in (("Öğretmenler", "ogretmen", data["teacher_columns"], "Öğretmen"),
                                       ("Sınıflar", "sinif", data["class_columns"], "Sınıf")):
        sheet = wb.create_sheet(title)
        head = [label]
        for _, short in columns:
            head += [f"{short} (bu)", f"{short} (diğer)", f"{short} farkı"]
        sheet.append(head)
        for cell in sheet[1]:
            cell.font = bold
        for p in data[key]:
            values = [p["name"]]
            for c in p["cells"]:
                values += [c["a"], c["b"], c["d"]]
            sheet.append(values)
            if p["status"] != "ayni":
                sheet.cell(sheet.max_row, 1).fill = worse if p["status"] == "kotu" else better
        sheet.column_dimensions["A"].width = 30
        sheet.freeze_panes = "B2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
