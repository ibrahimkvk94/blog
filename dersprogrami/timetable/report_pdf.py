"""Raporların doğrudan PDF çıktısı (reportlab): Excel çıktısıyla aynı veri, yazdırma penceresine gerek yok.

Türkçe karakterler için DejaVu Sans gömülür (timetable/fonts; Bitstream Vera/DejaVu lisansı serbesttir).
"""

from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepInFrame, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONTS = Path(__file__).resolve().parent / "fonts"
FONT, BOLD = "DejaVuSans", "DejaVuSans-Bold"
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(BOLD, str(FONTS / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=BOLD, italic=FONT, boldItalic=BOLD)

MARGIN = 10 * mm
HEAD = colors.HexColor("#EEF0FF")
LINE = colors.HexColor("#B9BFCA")
SIZES = {"kucuk": 7, "normal": 8.5, "buyuk": 10}
TITLE = ParagraphStyle("baslik", fontName=BOLD, fontSize=14, leading=17, spaceAfter=2, alignment=1)
INFO = ParagraphStyle("bilgi", fontName=FONT, fontSize=8.5, leading=11, textColor=colors.HexColor("#4B5563"), spaceAfter=4, alignment=1)


def _style(size, bold=False, center=False):
    return ParagraphStyle(f"h{size}{bold}{center}", fontName=BOLD if bold else FONT, fontSize=size,
                          leading=size * 1.18, alignment=1 if center else 0)


def _p(text, style):
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), style)


def _color(value, colored):
    if not colored or not value:
        return None
    try:
        color = colors.HexColor(value if value.startswith("#") else "#" + value)
    except (ValueError, AttributeError):
        return None
    return None if color.hexval().lower() == "0xffffff" else color


def _cards(cards, style):
    """Kart satırları: ders adı kalın, ayrıntılar altında; birden çok kart çizgiyle ayrılır."""
    parts = []
    for c in cards:
        lines = [escape(x) for x in c["lines"]]
        parts.append("<br/>".join([f"<b>{lines[0]}</b>"] + lines[1:]) if lines else "")
    return Paragraph("<br/>―<br/>".join(parts), style)


def _base(extra=()):
    return TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5), *extra,
    ])


def _header(title, subtitle=""):
    out = [_p(title, TITLE)]
    if subtitle:
        out.append(_p(subtitle, INFO))
    return out


def _table(headers, rows, widths, width, size):
    """Basit liste tablosu; genişlikler Excel sütun oranlarıyla, başlık her sayfada tekrar."""
    total = sum(widths)
    head, body = _style(size, bold=True), _style(size)
    data = [[_p(h, head) for h in headers]] + [[_p("" if v is None else v, body) for v in r] for r in rows]
    t = Table(data, colWidths=[width * w / total for w in widths], repeatRows=1)
    t.setStyle(_base([("BACKGROUND", (0, 0), (-1, 0), HEAD), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return [t] if rows else [t, Spacer(1, 4 * mm), _p("Seçime uygun kayıt yok.", INFO)]


def _individual(page, data, width, height, size, colored):
    """Tek varlığın programı: tek sayfaya sığana dek yazı küçülür, kalan boşluk satırlara dağıtılır."""
    o = data["o"]
    head = _header(page["title"], " · ".join(page["info"]))
    used = sum(f.wrap(width, height)[1] + f.getSpaceAfter() for f in head) + 2 * mm
    notes = [Spacer(1, 1.5 * mm), _p("Farklı saatli günler — " + " | ".join(data["time_notes"]), INFO)] if data.get("time_notes") and o["saat"] == "1" else []
    used += sum(f.wrap(width, height)[1] + f.getSpaceAfter() for f in notes)  # dipnot da aynı sayfaya sığsın
    room = height - used - 2
    first = 22 * mm
    columns = list(data["columns"])
    col_w = [first] + [(width - first) / max(len(columns), 1)] * len(columns)
    fs = size
    while True:
        hstyle, cstyle, bstyle = _style(fs, True, True), _style(fs, center=True), _style(fs, True)
        rows = [[_p("Gün" if o["gunler"] == "satir" else "Saat", hstyle)] + [_p(c, hstyle) for c in columns]]
        extra = []
        for i, r in enumerate(page["rows"], start=1):
            label = f"<b>{escape(r['head'])}</b>" + (f"<br/><font size={fs * 0.85:.1f}>{escape(r['sub'])}</font>" if r["sub"] else "")
            rows.append([Paragraph(label, bstyle)] + [_cards(cards, cstyle) for cards in r["cells"]])
            for j, cards in enumerate(r["cells"], start=1):
                fill = _color(cards[0]["color"], colored) if cards else None
                if fill:
                    extra.append(("BACKGROUND", (j, i), (j, i), fill))
        t = Table(rows, colWidths=col_w, repeatRows=1)
        h = t.wrap(width, room)[1]
        if h <= room or fs <= 4.5:
            break
        fs -= 0.5
    natural = list(t._rowHeights)
    if h < room and len(natural) > 1:  # satırları eşit yükseklikte sayfaya yay (dolu satırlar küçülmez)
        body = natural[1:]
        even = (room - natural[0]) / len(body)
        tall = [x for x in body if x > even]
        if len(tall) < len(body):
            even = (room - natural[0] - sum(tall)) / (len(body) - len(tall))
        t = Table(rows, colWidths=col_w, rowHeights=[natural[0]] + [max(x, even) for x in body], repeatRows=1)
    t.setStyle(_base([("BACKGROUND", (0, 0), (-1, 0), HEAD), ("BACKGROUND", (0, 1), (0, -1), HEAD), *extra]))
    if h > room:  # en küçük yazıyla da taşıyorsa tabloyu orantılı küçült: her zaman tek sayfa
        t = KeepInFrame(width, room, [t], mode="shrink")
    return head + [Spacer(1, 2 * mm), t] + notes


def _sheet(data, width, colored):
    """Çarşaf liste: sütunlar çok daralırsa günler sayfalara bölünür; başlık satırları tekrarlanır.
    Künye sütunları addan önce, ders adı/kodu addan sonra, saat sütunları en sonda (her sayfada)."""
    periods, days = data["periods"], list(data["sheet_days"])
    head_h, pre_h, post_h = data.get("lead_headers", []), data.get("pre_headers", []), data.get("post_headers", [])
    P = max(len(periods), 1)
    first = 24 * mm
    head_w = [16 * mm] * len(head_h)
    pre_w = [24 * mm if h == "Ders adı" else 14 * mm for h in pre_h]
    post_w = [12 * mm] * len(post_h)
    lead = len(head_h) + 1 + len(pre_h)
    fixed = sum(head_w) + first + sum(pre_w) + sum(post_w)
    per = max(1, min(len(days), int((width - fixed) / (P * 6 * mm))))
    col = (width - fixed) / (P * per)
    fs = max(4.5, min(7, col / mm * 0.62))
    hstyle, cstyle, tstyle = _style(fs + 0.5, True, True), _style(fs, center=True), _style(fs + 0.5, True)
    # Satır hücrelerini günlere ayır (birleşik hücreler gün sınırını aşmaz).
    split = []
    for r in data["sheet_rows"]:
        by_day = []
        for c in r["cells"]:
            if c["day_start"] or not by_day:
                by_day.append([])
            by_day[-1].append(c)
        split.append((r, by_day))
    out = []
    for start in range(0, len(days), per):
        chunk = days[start:start + per]
        top = [_p(h, hstyle) for h in head_h] + [_p("Ad Soyad" if head_h else "", hstyle)] + [_p(h, hstyle) for h in pre_h]
        nums = [""] * lead
        style = [("BACKGROUND", (0, 0), (-1, 1), HEAD), ("BACKGROUND", (0, 2), (len(head_h), -1), HEAD)]
        style += [("SPAN", (x, 0), (x, 1)) for x in range(lead)]
        for i, day in enumerate(chunk):
            top += [_p(day, hstyle)] + [""] * (P - 1)
            nums += [_p(p.index + 1, hstyle) for p in periods]
            style.append(("SPAN", (lead + i * P, 0), (lead + P - 1 + i * P, 0)))
        end = lead + len(chunk) * P
        top += [_p(h, hstyle) for h in post_h]
        nums += [""] * len(post_h)
        style += [("SPAN", (end + k, 0), (end + k, 1)) for k in range(len(post_h))]
        rows = [top, nums]
        for y, (r, by_day) in enumerate(split, start=2):
            line = ([_p(v, cstyle) for v in r.get("lead", [])] + [_p(r["title"], tstyle)]
                    + [_p(v, cstyle) for v in r.get("pre", [])])
            for i, cells in enumerate(by_day[start:start + per]):
                x = lead + i * P
                for c in cells:
                    line += [_cards(c["cards"], cstyle)] + [""] * (c["span"] - 1)
                    if c["span"] > 1:
                        style.append(("SPAN", (x, y), (x + c["span"] - 1, y)))
                    fill = _color(c["cards"][0]["color"], colored) if c["cards"] else None
                    if fill:
                        style.append(("BACKGROUND", (x, y), (x + c["span"] - 1, y), fill))
                    x += c["span"]
            line += [""] * (end - len(line))
            line += [_p(v, tstyle) for v in r.get("post", [])] + [""] * (len(post_h) - len(r.get("post", [])))
            rows.append(line)
        t = Table(rows, colWidths=head_w + [first] + pre_w + [col] * (P * len(chunk)) + post_w, repeatRows=2)
        t.setStyle(_base(style))
        if out:
            out.append(PageBreak())
        out.append(t)
    return out


def build(data):
    o = data["o"]
    kind = o["tur"]
    colored = o["renk"] == "1"
    size = SIZES.get(o["boyut"], 8.5)
    school, timetable = data["school"], data["timetable"]
    subtitle = f"{school} · {timetable.name}"
    pagesize = landscape(A4) if o["yon"] != "dikey" or kind in ("carsaf", "carsaf_gun") else portrait(A4)
    sign = o["imza"]
    sign_h = (len(sign) * 11 + 6 * mm) if sign else 0  # imza satırları (en fazla 3) ve imza boşluğu
    width, height = pagesize[0] - 2 * MARGIN - 12, pagesize[1] - 2 * MARGIN - 8 * mm - sign_h - 12  # çerçeve iç boşluğu + alt bilgi
    story = []

    if kind == "bireysel":
        for group in data["pages"]:
            for page in group:
                if story:
                    story.append(PageBreak())
                story += _individual(page, data, width, height, size, colored)
    elif kind in ("carsaf", "carsaf_gun"):
        if data["sheet_rows"]:
            story = _header(o["baslik"] or data["kind_label"], subtitle) + _sheet(data, width, colored)
    elif kind == "yuk":
        rows = []
        for r in data["load_rows"]:
            for lesson in r["lessons"] or [{"subject": "–", "classes": "", "groups": "", "hours": 0, "split": ""}]:
                rows.append([*r["kunye"], r["name"], lesson["subject"], lesson["classes"], lesson["groups"], lesson["hours"],
                             lesson["split"], r["total"], r["target"] or "", r["diff"] if r["diff"] is not None else ""])
        story = _header(o["baslik"] or "Öğretmen ders yükü", subtitle) + _table(
            [*data["kunye_headers"], "Öğretmen", "Ders", "Sınıf", "Grup", "Saat", "Dağılım", "Toplam", "Hedef", "Fark"], rows,
            [*[14] * len(data["kunye_headers"]), 26, 30, 20, 16, 7, 10, 8, 8, 7], width, size)
    elif kind == "sinif_dersleri":
        rows = [[r["title"], lesson["subject"], lesson["teachers"], lesson["groups"], lesson["hours"], lesson["split"]]
                for r in data["class_rows"] for lesson in r["lessons"]]
        story = _header(o["baslik"] or "Sınıf ders listesi", subtitle) + _table(
            ["Kısım", "Ders", "Öğretmen", "Grup", "Saat", "Dağılım"], rows, [12, 32, 30, 16, 7, 10], width, size)
    elif kind in ("bos_derslik", "bos_ogretmen"):
        headers = ["Gün"] + [f"{p.index + 1}." for p in data["periods"]]
        rows = [[r["day"]] + [", ".join(names) for names in r["cells"]] for r in data["free_rows"]]
        story = _header(o["baslik"] or data["free_label"], data.get("free_note", subtitle)) + _table(
            headers, rows, [12] + [22] * len(data["periods"]), width, min(size, 7.5))
    elif kind == "nobet":
        duty = data["duty"]
        rows = [[r["place"].name] + [", ".join(d.teacher.full_name for d in c["duties"]) for c in r["cells"]] for r in duty["rows"]]
        story = _header(o["baslik"] or "Nöbet çizelgesi", str(school)) + _table(
            ["Nöbet yeri"] + list(duty["days"]), rows, [20] + [26] * len(duty["days"]), width, size)
    elif kind == "uybs":
        info = f"{o['hafta_tarih']:%d.%m.%Y} haftası · " if o["hafta_tarih"] else ""
        headers = ["Kısım", "Kısım adı", "Ders kodu", "Ders", "Grup", "Öğretmen", "Gün", "Tarih", "Saat", "Saat aralığı", "Sıra", "ÜYBS ref", "Derslik"]
        rows = [[r["class"], r["class_name"], r["code"], r["subject"], r["groups"], r["teachers"], r["day"],
                 r["date"].strftime("%d.%m.%Y") if r["date"] else "", r["period"], r["time"], r["ordinal"], r["ref"], r["room"]]
                for r in data["uybs_rows"]]
        story = _header(o["baslik"] or "ÜYBS aktarım listesi", info + subtitle) + _table(
            headers, rows, [9, 14, 11, 34, 14, 26, 11, 11, 6, 13, 6, 12, 16], width, min(size, 7))
    if not story:
        story = _header(o["baslik"] or data["type_label"], subtitle) + [_p("Seçime uygun kayıt yok.", INFO)]

    def footer(canvas, doc):  # her sayfada okul/program, imza ve sayfa numarası
        canvas.saveState()
        canvas.setFont(FONT, 7)
        canvas.setFillColor(colors.HexColor("#6B7280"))
        canvas.drawString(MARGIN, MARGIN, subtitle)
        canvas.drawRightString(pagesize[0] - MARGIN, MARGIN, f"Sayfa {doc.page}")
        x = pagesize[0] - MARGIN - 35 * mm
        for i, line in enumerate(sign):  # imza bloğu sağda, satırlar alt alta (ilki kalın)
            canvas.setFont(BOLD if i == 0 else FONT, 9)
            canvas.setFillColor(colors.black)
            canvas.drawCentredString(x, MARGIN + 6 * mm + (len(sign) - 1 - i) * 11, line)
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=pagesize, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN,
                            bottomMargin=MARGIN + 8 * mm + sign_h, title=o["baslik"] or data["type_label"], author=str(school))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
