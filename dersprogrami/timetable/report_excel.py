"""Raporların Excel çıktısı: ekrandaki rapor ayarlarıyla aynı içerik, her rapor türü için uygun düzen."""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

TITLE = Font(bold=True, size=14)
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="EEF0FF")
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
THIN = Side(style="thin", color="B9BFCA")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _fill(color, colored):
    if not colored or not color:
        return None
    return PatternFill("solid", fgColor=color.lstrip("#").upper())


def _sheet(wb, title):
    name = "".join(ch for ch in title if ch not in '[]:*?/\\')[:31] or "Rapor"
    existing = {ws.title for ws in wb.worksheets}
    base, n = name, 2
    while name in existing:
        name = f"{base[:28]}-{n}"
        n += 1
    return wb.create_sheet(name)


def _header(ws, title, subtitle=""):
    ws.cell(row=1, column=1, value=title).font = TITLE
    if subtitle:
        ws.cell(row=2, column=1, value=subtitle)
    return 4


def _table(ws, row, headers, rows, widths=None):
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=c, value=h)
        cell.font, cell.fill, cell.border = BOLD, HEAD, BOX
    for r in rows:
        row += 1
        for c, value in enumerate(r, start=1):
            cell = ws.cell(row=row, column=c, value=value)
            cell.border, cell.alignment = BOX, WRAP
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=row - len(rows) + 1 if rows else row + 1, column=1)
    return row + 2


def _lines(cards):
    return "\n".join(" · ".join(c["lines"]) for c in cards)


def build(data):
    o = data["o"]
    wb = Workbook()
    wb.remove(wb.active)
    colored = o["renk"] == "1"
    school, timetable = data["school"], data["timetable"]
    subtitle = f"{school} · {timetable.name}"
    kind = o["tur"]

    if kind == "bireysel":
        for group in data["pages"]:
            for page in group:
                ws = _sheet(wb, page["title"])
                row = _header(ws, page["title"], " · ".join(page["info"]))
                headers = ["Gün" if o["gunler"] == "satir" else "Saat"] + list(data["columns"])
                for c, h in enumerate(headers, start=1):
                    cell = ws.cell(row=row, column=c, value=str(h))
                    cell.font, cell.fill, cell.border, cell.alignment = BOLD, HEAD, BOX, CENTER
                for r in page["rows"]:
                    row += 1
                    head = ws.cell(row=row, column=1, value=f"{r['head']} {r['sub']}".strip())
                    head.font, head.border, head.alignment = BOLD, BOX, WRAP
                    for c, cards in enumerate(r["cells"], start=2):
                        cell = ws.cell(row=row, column=c, value=_lines(cards))
                        cell.border, cell.alignment = BOX, WRAP
                        fill = _fill(cards[0]["color"], colored) if cards else None
                        if fill:
                            cell.fill = fill
                    ws.row_dimensions[row].height = 42
                ws.column_dimensions["A"].width = 14
                for c in range(2, len(headers) + 1):
                    ws.column_dimensions[get_column_letter(c)].width = 24
    elif kind in ("carsaf", "carsaf_gun"):
        ws = _sheet(wb, data["kind_label"])
        row = _header(ws, o["baslik"] or data["kind_label"], subtitle)
        periods = data["periods"]
        P = len(periods)
        for i, day in enumerate(data["sheet_days"]):
            col = 2 + i * P
            ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + P - 1)
            cell = ws.cell(row=row, column=col, value=day)
            cell.font, cell.fill, cell.alignment = BOLD, HEAD, CENTER
            for j, p in enumerate(periods):
                c = ws.cell(row=row + 1, column=col + j, value=p.index + 1)
                c.font, c.fill, c.alignment, c.border = BOLD, HEAD, CENTER, BOX
        row += 1
        for r in data["sheet_rows"]:
            row += 1
            ws.cell(row=row, column=1, value=r["title"]).font = BOLD
            col = 2
            for cell_data in r["cells"]:
                if cell_data["span"] > 1:
                    ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + cell_data["span"] - 1)
                cell = ws.cell(row=row, column=col, value=_lines(cell_data["cards"]))
                cell.alignment, cell.border = CENTER, BOX
                fill = _fill(cell_data["cards"][0]["color"], colored) if cell_data["cards"] else None
                if fill:
                    cell.fill = fill
                col += cell_data["span"]
            ws.row_dimensions[row].height = 30
        ws.column_dimensions["A"].width = 12
        for c in range(2, 2 + P * len(data["sheet_days"])):
            ws.column_dimensions[get_column_letter(c)].width = 9
        ws.freeze_panes = "B6"
    elif kind == "yuk":
        ws = _sheet(wb, "Ders yükü")
        row = _header(ws, o["baslik"] or "Öğretmen ders yükü", subtitle)
        rows = []
        for r in data["load_rows"]:
            for lesson in r["lessons"] or [{"subject": "–", "classes": "", "groups": "", "hours": 0, "split": ""}]:
                rows.append([r["teacher"].full_name, lesson["subject"], lesson["classes"], lesson["groups"], lesson["hours"],
                             lesson["split"], r["total"], r["target"] or "", r["diff"] if r["diff"] is not None else ""])
        _table(ws, row, ["Öğretmen", "Ders", "Sınıf", "Grup", "Saat", "Dağılım", "Toplam", "Hedef", "Fark"], rows,
               [26, 30, 20, 16, 7, 10, 8, 8, 7])
    elif kind == "sinif_dersleri":
        ws = _sheet(wb, "Sınıf dersleri")
        row = _header(ws, o["baslik"] or "Sınıf ders listesi", subtitle)
        rows = [[r["title"], lesson["subject"], lesson["teachers"], lesson["groups"], lesson["hours"], lesson["split"]]
                for r in data["class_rows"] for lesson in r["lessons"]]
        _table(ws, row, ["Kısım", "Ders", "Öğretmen", "Grup", "Saat", "Dağılım"], rows, [12, 32, 30, 16, 7, 10])
    elif kind in ("bos_derslik", "bos_ogretmen"):
        ws = _sheet(wb, data["free_label"])
        row = _header(ws, o["baslik"] or data["free_label"], data.get("free_note", subtitle))
        headers = ["Gün"] + [f"{p.index + 1}." for p in data["periods"]]
        rows = [[r["day"]] + [", ".join(names) for names in r["cells"]] for r in data["free_rows"]]
        _table(ws, row, headers, rows, [12] + [22] * len(data["periods"]))
    elif kind == "nobet":
        ws = _sheet(wb, "Nöbet")
        row = _header(ws, o["baslik"] or "Nöbet çizelgesi", str(school))
        duty = data["duty"]
        rows = [[r["place"].name] + [", ".join(d.teacher.full_name for d in c["duties"]) for c in r["cells"]] for r in duty["rows"]]
        _table(ws, row, ["Nöbet yeri"] + list(duty["days"]), rows, [20] + [26] * len(duty["days"]))
    elif kind == "uybs":
        ws = _sheet(wb, "ÜYBS")
        info = f"{o['hafta_tarih']:%d.%m.%Y} haftası · " if o["hafta_tarih"] else ""
        row = _header(ws, o["baslik"] or "ÜYBS aktarım listesi", info + subtitle)
        headers = ["Kısım", "Kısım adı", "Ders kodu", "Ders", "Grup", "Öğretmen", "Gün", "Tarih", "Saat", "Saat aralığı", "Sıra", "ÜYBS ref", "Derslik"]
        rows = [[r["class"], r["class_name"], r["code"], r["subject"], r["groups"], r["teachers"], r["day"],
                 r["date"].strftime("%d.%m.%Y") if r["date"] else "", r["period"], r["time"], r["ordinal"], r["ref"], r["room"]]
                for r in data["uybs_rows"]]
        _table(ws, row, headers, rows, [9, 14, 11, 34, 14, 26, 11, 11, 6, 13, 6, 12, 16])
    if not wb.worksheets:
        _sheet(wb, "Rapor").cell(row=1, column=1, value="Seçime uygun kayıt yok.")
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
