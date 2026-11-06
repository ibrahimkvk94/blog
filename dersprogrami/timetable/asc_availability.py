"""aSc öğretmen listesinden müsaitlik (mazeret) aktarımı.

aSc'nin çevrim içi sürümünde Öğretmenler tablosunun "Zaman Tablosu" sütunu her öğretmenin haftalık ızgarasını
renkli kutularla gösterir: her gün bir satır (div.row), her ders saati bir kutu; kırmızı = gelemez, sarı =
koşullu (?), yeşil = gelebilir. Tablonun HTML'i yapıştırılır; öğretmenler kısa ad ya da ad soyadla eşleştirilir,
ön izlemeden sonra seçilenlerin müsaitliği bu ızgarayla değiştirilir.
"""

import re
from html.parser import HTMLParser

from .data_views import apply_availability
from .models import Availability, Teacher

GRID_COLUMN = "zaman tablosu"
COLUMNS = {"first": "isim", "last": "soy isim", "short": "kısaltma"}


def _key(text):
    """Karşılaştırma anahtarı: Türkçe küçük harf, tek boşluk."""
    text = (text or "").replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"\s+", " ", text).strip()


def _state(style):
    """Kutunun arka plan renginden durum: "no" (kırmızı), "maybe" (sarı / turuncu), "" (yeşil, beyaz)."""
    m = re.search(r"background(?:-color)?\s*:\s*rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", style or "", re.I)
    if not m:
        m2 = re.search(r"background(?:-color)?\s*:\s*#([0-9a-f]{6})", style or "", re.I)
        if not m2:
            return None
        r, g, b = (int(m2[1][i:i + 2], 16) for i in (0, 2, 4))
    else:
        r, g, b = (int(x) for x in m.groups())
    if r >= 180 and g < 120 and b < 120:
        return Availability.NO
    if r >= 180 and g >= 150 and b < 120:
        return Availability.MAYBE
    return ""


class _Table(HTMLParser):
    """Başlıkları ve her satırın hücre metinleriyle ızgarasını okur."""

    def __init__(self):
        super().__init__()
        self.headers, self.rows = [], []
        self.row = self.cell = None
        self.in_th = self.in_style = False
        self.th_text = []
        self.div_stack = []  # her açık div için: "row" (gün satırı), "box" (saat kutusu) ya da ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "th":
            self.in_th, self.th_text = True, [attrs.get("title") or ""]
        elif tag == "tr":
            self.row = {"cells": [], "grids": []}
        elif tag == "td" and self.row is not None:
            self.cell = {"text": [], "grid": []}
        elif tag == "style":
            self.in_style = True
        elif tag == "div" and self.cell is not None:
            kind = ""
            if "row" in (attrs.get("class") or "").split():
                self.cell["grid"].append([])
                kind = "row"
            elif self.div_stack and self.div_stack[-1] == "row":
                state = _state(attrs.get("style"))
                if state is not None:
                    self.cell["grid"][-1].append(state)
                kind = "box"
            self.div_stack.append(kind)

    def handle_endtag(self, tag):
        if tag == "th" and self.in_th:
            self.headers.append(" ".join("".join(self.th_text).split()))
            self.in_th = False
        elif tag == "style":
            self.in_style = False
        elif tag == "div" and self.div_stack:
            self.div_stack.pop()
        elif tag == "td" and self.cell is not None and self.row is not None:
            self.row["cells"].append(" ".join("".join(self.cell["text"]).split()))
            self.row["grids"].append(self.cell["grid"])
            self.cell, self.div_stack = None, []
        elif tag == "tr" and self.row is not None:
            if self.row["cells"]:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_style:
            return
        if self.in_th and not self.th_text[0]:
            self.th_text.append(data)
        elif self.cell is not None:
            self.cell["text"].append(data)


def parse(text):
    """[{"first", "last", "short", "grid": [[durum, ...] gün başına]}] — ızgarası olan satırlar."""
    parser = _Table()
    parser.feed(text or "")
    keys = [_key(h) for h in parser.headers]
    index = {name: keys.index(title) for name, title in COLUMNS.items() if title in keys}
    grid_at = keys.index(GRID_COLUMN) if GRID_COLUMN in keys else None
    out = []
    for row in parser.rows:
        cells, grids = row["cells"], row["grids"]
        column = grid_at if grid_at is not None and grid_at < len(grids) and grids[grid_at] else next(
            (i for i, g in enumerate(grids) if g), None)
        if column is None:
            continue
        get = lambda name, default: cells[index[name]] if name in index and index[name] < len(cells) else (  # noqa: E731
            cells[default] if default < len(cells) else "")
        out.append({"first": get("first", 2), "last": get("last", 3), "short": get("short", 4),
                    "grid": [day for day in grids[column] if day]})
    return out


def _states(school, grid, periods):
    """aSc ızgarası → {(gün, saat): durum} (programın gün ve saat sayısıyla sınırlı)."""
    return {(d, p): state for d, day in enumerate(grid[:school.days_per_week]) for p, state in enumerate(day[:periods])
            if state}


def plan(school, rows):
    """Her satır için eşleşen öğretmen ve değişiklik özeti."""
    teachers = list(Teacher.objects.filter(school=school))
    by_short = {_key(t.short): t for t in teachers if t.short}
    by_name = {_key(t.full_name): t for t in teachers}
    periods = school.periods.count()
    current = {}
    for a in Availability.objects.filter(school=school, teacher__isnull=False):
        current.setdefault(a.teacher_id, {})[(a.day, a.period)] = a.state
    out = []
    for i, row in enumerate(rows):
        name = f"{row['first']} {row['last']}".strip()
        teacher = by_short.get(_key(row["short"])) or by_name.get(_key(name))
        item = {"index": i, "name": name or row["short"], "short": row["short"], "teacher": teacher, "error": "", "warning": ""}
        if teacher is None:
            item["error"] = "Programda bu ada ya da kısa ada sahip öğretmen yok."
            out.append(item)
            continue
        days, width = len(row["grid"]), max((len(d) for d in row["grid"]), default=0)
        if days != school.days_per_week or width != periods:
            item["warning"] = (f"aSc ızgarası {days} gün × {width} saat, program {school.days_per_week} × {periods}; "
                               "fazla gün/saat yok sayılır, eksikler açık kalır.")
        new, old = _states(school, row["grid"], periods), current.get(teacher.pk, {})
        cells = set(new) | set(old)
        item.update({
            "states": new,
            "closed": sum(1 for c in new if new[c] == Availability.NO),
            "maybe": sum(1 for c in new if new[c] == Availability.MAYBE),
            "changed": sum(1 for c in cells if new.get(c) != old.get(c)),
            "grid": [[{"state": new.get((d, p), ""), "changed": new.get((d, p)) != old.get((d, p))}
                      for p in range(periods)] for d in range(school.days_per_week)],
        })
        out.append(item)
    # Aynı öğretmene birden çok satır düşerse yalnızca ilki aktarılır.
    seen = set()
    for item in out:
        if item["teacher"] is not None:
            if item["teacher"].pk in seen:
                item["error"] = "Bu öğretmen listede daha önce geçti."
            seen.add(item["teacher"].pk)
    return out


def apply(school, items):
    """Seçilen satırlardaki öğretmenlerin müsaitliğini aSc ızgarasıyla değiştirir. Dönüş: güncellenen öğretmen sayısı."""
    n = 0
    for item in items:
        if item["teacher"] is not None and not item["error"]:
            apply_availability(school, "teacher", [item["teacher"]], item["states"], mode="replace")
            n += 1
    return n
