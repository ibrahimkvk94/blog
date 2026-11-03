"""Aylık nöbet gruplarının EK-3 düzeninde Excel çıktısı."""

from collections import defaultdict
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import AYLAR, NobetGorevi
from .servis import muaf_personel

RENK = {"mavi": "5B9BD5", "turuncu": "F4B183", "yesil": "70AD47", "kirmizi": "E06666", "sari": "FFE699", "gri": "BFBFBF"}
INCE = Side(style="thin", color="808080")
KENAR = Border(left=INCE, right=INCE, top=INCE, bottom=INCE)


def ek3(donem):
    wb = Workbook()
    ws = wb.active
    ws.title = "EK-3 NÖBET GRUPLARI"
    gorevler = list(NobetGorevi.objects.filter(aktif=True).order_by("sira", "ad"))
    kisiler = defaultdict(list)
    for a in donem.atamalar.select_related("personel__rutbe", "personel__sinif", "personel__unvan").order_by("personel__ad_soyad"):
        kisiler[a.gorev_id].append(a.personel)

    yazi = Font(name="Times New Roman", size=10)
    kalin = Font(name="Times New Roman", size=10, bold=True)
    orta = Alignment(horizontal="center", vertical="center", wrap_text=True)

    son_sutun = len(gorevler) + 1
    ws.cell(row=1, column=1, value=f"{AYLAR[donem.ay - 1].upper()} {donem.yil} NÖBET GRUPLARI").font = Font(name="Times New Roman", size=14, bold=True)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=son_sutun)
    ws.cell(row=1, column=1).alignment = orta

    ws.cell(row=2, column=1, value="S.NU.").font = kalin
    ws.column_dimensions["A"].width = 5
    en_uzun = max((len(kisiler[g.pk]) for g in gorevler), default=0)
    for i, g in enumerate(gorevler, start=2):
        baslik = g.ad.upper() + (f"\n({g.aciklama})" if g.aciklama else "")
        c = ws.cell(row=2, column=i, value=baslik)
        c.font, c.alignment, c.border = kalin, orta, KENAR
        c.fill = PatternFill("solid", fgColor=RENK.get(g.renk, "BFBFBF"))
        ws.column_dimensions[get_column_letter(i)].width = 26
        for j, p in enumerate(kisiler[g.pk], start=3):
            hucre = ws.cell(row=j, column=i, value=p.tam_ad)
            hucre.font, hucre.border = yazi, KENAR
    ws.row_dimensions[2].height = 60
    for j in range(en_uzun):
        ws.cell(row=3 + j, column=1, value=j + 1).font = yazi

    # Muaf / tutamaz personel, nedenlerine göre
    satir = 3 + en_uzun + 2
    gruplar = defaultdict(list)
    for p in muaf_personel(donem):
        neden = p.muaf_nedeni
        gruplar[neden.upper()].append(p)
    for i, (neden, liste) in enumerate(sorted(gruplar.items()), start=2):
        c = ws.cell(row=satir, column=i, value=neden)
        c.font, c.alignment, c.border = kalin, orta, KENAR
        c.fill = PatternFill("solid", fgColor="BDD7EE")
        for j, p in enumerate(liste, start=1):
            ws.cell(row=satir + j, column=i, value=p.tam_ad).font = yazi

    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    cikti = BytesIO()
    wb.save(cikti)
    return cikti.getvalue()
