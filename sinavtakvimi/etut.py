"""Etüt görevlendirmeleri (Sınav İcrası 3. sekme): sınav gününden bir önceki gün (hafta içi / sonu fark etmez) etüde
gelecek öğretim elemanları. Planın her ders × program satırına bir kişi yazılır, isteğe bağlı ikincisi eklenir. Herkes
görür; bölüm hesabı kendi programının ya da verdiği dersin satırını, Sınav İcrası yetkilisi hepsini girer. Öneri,
kesinleştirme ve puantaj yoktur."""

import datetime
import io

from django.db import transaction

from personel.models import Personel

from . import servis
from .models import Etut


def adaylar():
    """Seçilebilecek öğretim elemanları: okulun derse giren tüm aktif personeli."""
    return list(Personel.objects.filter(aktif=True, derse_girebilir=True)
                .select_related("bolum", "unvan", "rutbe", "sinif").order_by("ad_soyad"))


def kisi_sozlugu(p):
    return {"id": p.pk, "ad": str(p), "bolum": (p.bolum.kod or p.bolum.ad) if p.bolum_id else ""} if p else None


def satirlar(takvim, yetki=None):
    """Planın her ders × program satırı (bir kez) ve yazılan öğretim elemanları; etüt günü = sınavdan önceki gün."""
    from personel.models import Bolum

    kayitlar = {(e.kod, e.bolum): e for e in takvim.etutler.select_related(
        "ogretmen1__unvan", "ogretmen1__rutbe", "ogretmen1__sinif", "ogretmen1__bolum",
        "ogretmen2__unvan", "ogretmen2__rutbe", "ogretmen2__sinif", "ogretmen2__bolum")}
    bolumler = servis.ders_bolumleri()
    adlar = dict(Bolum.objects.exclude(kod=None).values_list("kod", "ad"))
    out, gorulen = [], set()
    for s in takvim.satirlar.all():
        anahtar = (s.kod, s.bolum)
        if anahtar in gorulen or not s.kod:
            continue
        gorulen.add(anahtar)
        e = kayitlar.get(anahtar)
        o = servis.onek(s.kod)
        db = bolumler.get(o)
        o1 = e.ogretmen1 if e else None
        o2 = e.ogretmen2 if e else None
        etut_gunu = s.tarih - datetime.timedelta(days=1)
        out.append({"no": len(out) + 1, "satir": s, "kod": s.kod, "ders": s.ders, "ad": servis.tr_baslik(s.ders),
                    "bolum": s.bolum, "bolum_adi": adlar.get(s.bolum, s.bolum), "sinif": s.sinif,
                    "ders_bolumu": db.kod if db and db.kod else o, "ders_bolumu_adi": db.ad if db else o,
                    "etut_gunu": etut_gunu, "o1": o1, "o2": o2, "girildi": o1 is not None,
                    "girebilir": yetki.girebilir(s.bolum, o) if yetki else False})
    return out


def gunler(satir_listesi):
    """Etüt günleri (sırayla) ve her günün dolu / toplam sayısı."""
    out = {}
    for r in satir_listesi:
        g = out.setdefault(r["etut_gunu"], {"tarih": r["etut_gunu"], "toplam": 0, "girilen": 0,
                                              "ad": servis.GUNLER[r["etut_gunu"].weekday()],
                                              "sinav_gunu": r["satir"].tarih})
        g["toplam"] += 1
        g["girilen"] += r["girildi"]
    return [out[k] for k in sorted(out)]


@transaction.atomic
def kaydet(takvim, kod, bolum, ogretmen1, ogretmen2, user):
    """ogretmen1/2: Personel kimliği ya da None. İkinci tek başına kalırsa birinci olur; aynı kişi iki kez yazılmaz."""
    gecerli = set(Personel.objects.filter(aktif=True, derse_girebilir=True).values_list("pk", flat=True))
    idler = []
    for x in (ogretmen1, ogretmen2):
        try:
            x = int(x) if x not in (None, "") else None
        except (TypeError, ValueError):
            raise servis.TakvimHatasi("Öğretim elemanı geçersiz.") from None
        if x is not None:
            if x not in gecerli:
                raise servis.TakvimHatasi("Bu kişi seçilebilecek öğretim elemanları arasında değil.")
            if x not in idler:
                idler.append(x)
    if not idler:
        Etut.objects.filter(takvim=takvim, kod=kod, bolum=bolum).delete()
        return None
    e, _ = Etut.objects.update_or_create(takvim=takvim, kod=kod, bolum=bolum, defaults={
        "ogretmen1_id": idler[0], "ogretmen2_id": idler[1] if len(idler) > 1 else None, "guncelleyen": user})
    return Etut.objects.select_related("ogretmen1__unvan", "ogretmen1__rutbe", "ogretmen1__sinif", "ogretmen1__bolum",
                                       "ogretmen2__unvan", "ogretmen2__rutbe", "ogretmen2__sinif",
                                       "ogretmen2__bolum").get(pk=e.pk)


def excel(takvim, satir_listesi):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Etüt"
    yazi, kalin = Font(name="Times New Roman", size=12), Font(name="Times New Roman", size=12, bold=True)
    ince = Side(style="thin", color="000000")
    cerceve = Border(left=ince, right=ince, top=ince, bottom=ince)
    orta = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sol = Alignment(horizontal="left", vertical="center", wrap_text=True)
    basliklar = ["S.NO", "ETÜT GÜNÜ", "SINAV TARİHİ", "SINIF", "DERS KODU", "DERS ADI", "SINAVIN YAPILACAĞI PROGRAM",
                 "ETÜT ÖĞRETİM ELEMANI", "2. ÖĞRETİM ELEMANI"]
    genislik = [7, 20, 14, 7, 12, 44, 34, 36, 36]
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(basliklar))
    ws.cell(1, 1, f"{takvim.ad.upper()} — ETÜT GÖREVLENDİRMELERİ").font = Font(name="Times New Roman", size=13, bold=True)
    ws.cell(1, 1).alignment = orta
    ws.row_dimensions[1].height = 30
    gri = PatternFill("solid", fgColor="D9D9D9")
    for j, b in enumerate(basliklar, start=1):
        c = ws.cell(2, j, b)
        c.font, c.alignment, c.border, c.fill = kalin, orta, cerceve, gri
        ws.column_dimensions[get_column_letter(j)].width = genislik[j - 1]
    for i, r in enumerate(satir_listesi, start=3):
        g = r["etut_gunu"]
        degerler = [i - 2, f"{g:%d.%m.%Y} {servis.GUNLER[g.weekday()]}", f"{r['satir'].tarih:%d.%m.%Y}", r["sinif"],
                    r["kod"], r["ders"], r["bolum_adi"].upper(), str(r["o1"]) if r["o1"] else "",
                    str(r["o2"]) if r["o2"] else ""]
        for j, v in enumerate(degerler, start=1):
            c = ws.cell(i, j, v)
            c.font, c.border, c.alignment = yazi, cerceve, (sol if j in (6, 7, 8, 9) else orta)
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:I{max(len(satir_listesi) + 2, 2)}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
