"""Günlük personel yoklama formu (kurumun resmî biçimi): sayım tablosu + gayri mevcut beyanı.

Sütunlar: General/Amiral · Öğretim elemanı (sivil / subay / astsubay) · Subay · Astsubay · Sivil memur · Genel toplam.
Satırlar: Genel mevcut (aktif personel) · Gayri mevcut (o gün GÜN BOYU kaydı olan) · Hazır mevcut (fark).
Saatlik kayıtlar (ör. 13:00–15:00) mesaiye katılan personeldir; forma girmez, ekranda ayrıca gösterilir.

Grup künyeden otomatik bulunur; idari işler yetkilisi "Yoklama grupları" sayfasından kişi bazında değiştirebilir.
"""

import datetime

from django.conf import settings
from django.http import HttpResponse

from personel.models import AKADEMIK_UNVANLAR, MEMUR_UNVANLARI

from . import servis
from .models import PersonelGrubu

G = PersonelGrubu
SUTUNLAR = [G.GENERAL, G.OE_SIVIL, G.OE_SUBAY, G.OE_ASTSUBAY, G.SUBAY, G.ASTSUBAY, G.SIVIL_MEMUR]
GRUP_ADI = dict(G.GRUPLAR)

GENERAL_RUTBELERI = {"Tuğg.", "Tümg.", "Korg.", "Org.", "Tuğa.", "Tüma.", "Kora.", "Ora.", "Mrşl."}
UST_BASLIK = getattr(settings, "YOKLAMA_FORMU_UST_BASLIK",
                     ["T.C.", "MİLLİ SAVUNMA BAKANLIĞI", "Milli Savunma Üniversitesi"])
EN_COK_GUN = 31  # Excel'de bir dosyada en fazla bu kadar gün (her gün ayrı sayfa)
EN_AZ_BEYAN_SATIRI = 20


def tr_buyuk(metin):
    return (metin or "").replace("i", "İ").replace("ı", "I").upper()


def otomatik_grup(p):
    rutbe = str(p.rutbe or "").strip()
    sinif = str(p.sinif or "").strip()
    akademik = str(p.unvan or "").strip() in AKADEMIK_UNVANLAR
    ogretim = bool(p.bolum_id) or sinif == "Öğ." or akademik
    if not rutbe:
        # bölüm başkanlığında çalışan De.Me. / VHKİ öğretim elemanı sayılmaz
        memur = str(p.unvan or "").strip() in MEMUR_UNVANLARI
        return G.OE_SIVIL if ogretim and not memur else G.SIVIL_MEMUR
    if rutbe in GENERAL_RUTBELERI:
        return G.GENERAL
    astsubay = rutbe.startswith("Asb.") or rutbe.startswith("Yd.Asb.")
    if ogretim:
        return G.OE_ASTSUBAY if astsubay else G.OE_SUBAY
    return G.ASTSUBAY if astsubay else G.SUBAY


def otomatik_gorev(p, grup):
    """Kadro görevi (görev unvanı → De.Me./VHKİ → "Fizik Öğretim Görevlisi"); yoksa öğretim elemanında bölümüyle."""
    ogretim = grup in (G.OE_SIVIL, G.OE_SUBAY, G.OE_ASTSUBAY)
    gorev = p.kadro_gorevi_metni(ogretim=ogretim)
    if gorev or not ogretim:
        return gorev
    return f"Öğretim Elemanı ({p.bolum.kod or p.bolum.ad})" if p.bolum_id else "Öğretim Elemanı"


def atamalar(kisiler):
    return {a.personel_id: a for a in PersonelGrubu.objects.filter(personel_id__in=[p.pk for p in kisiler])}


def grup_ve_gorev(p, atama=None):
    grup = (atama.grup if atama and atama.grup else None) or otomatik_grup(p)
    gorev = (atama.gorev if atama and atama.gorev else None) or otomatik_gorev(p, grup)
    return grup, gorev


def _rapor_sirasi(tur):
    """İzin türünün rapor sırası (1 en başta). Sırası verilmemiş türler sonda ve kendi aralarında türe göre değil
    eskisi gibi grup ve kıdeme göre sıralanır; aynı sıradaki türlerde de grup/kıdem geçerlidir."""
    return tur.rapor_sirasi if tur.rapor_sirasi is not None else 10 ** 4


def _tarih_metni(an):
    return f"{an:%d.%m.%Y}" if an.hour == an.minute == 0 else f"{an:%d.%m.%Y %H:%M}"


def gunluk(tarih, kisiler, birim=None, ata=None):
    """Bir günün formu: {tarih, baslik, sayim: [{ad, degerler: [..8]}], beyan: [satır], saatlik: [satır]}."""
    ata = atamalar(kisiler) if ata is None else ata
    bas, bit = servis.gun_araligi(tarih)
    genel = dict.fromkeys(SUTUNLAR, 0)
    gayri = dict.fromkeys(SUTUNLAR, 0)
    beyan, saatlik = [], []
    for d in servis.gun_durumu(tarih, kisiler):
        p = d.personel
        grup, gorev = grup_ve_gorev(p, ata.get(p.pk))
        genel[grup] += 1
        if d.mevcut:
            continue
        sira = (SUTUNLAR.index(grup), -(p.rutbe.sira if p.rutbe else -1), p.ad_soyad)
        if d.gun_boyu:
            gayri[grup] += 1
            k = next(k for k in d.kayitlar if k.baslangic <= bas and k.bitis >= bit)
            sira = (_rapor_sirasi(k.tur),) + sira
            beyan.append({"sira": sira, "personel": p, "kimlik": p.tam_ad, "gorev": gorev, "sebep": k.tur.ad,
                          "ayrilis": _tarih_metni(k.yerel_bas), "katilis": _tarih_metni(k.yerel_bit), "kayit": k})
        else:
            for k in d.kayitlar:
                saatlik.append({"sira": (_rapor_sirasi(k.tur),) + sira, "personel": p, "kimlik": p.tam_ad, "sebep": k.tur.ad,
                                "aralik": f"{k.yerel_bas:%H:%M}–{k.yerel_bit:%H:%M}", "kayit": k})
    beyan.sort(key=lambda s: s["sira"])
    saatlik.sort(key=lambda s: s["sira"])

    def satir(ad, sayilar):
        degerler = [sayilar[s] for s in SUTUNLAR]
        return {"ad": ad, "degerler": degerler + [sum(degerler)]}

    hazir = {s: genel[s] - gayri[s] for s in SUTUNLAR}
    kurum = tr_buyuk(f"{settings.KURUM_ADI} Müdürlüğü")
    return {
        "tarih": tarih, "birim": birim,
        "ust_baslik": [*UST_BASLIK, f"{settings.KURUM_ADI} Müdürlüğü"],
        "baslik": f"{kurum} " + (f"{tr_buyuk(servis.birim_basligi(birim))} " if birim else "") + "PERSONEL YOKLAMASI (GÜNLÜK)",
        "sayim": [satir("GENEL MEVCUT", genel), satir("GAYRİ MEVCUT", gayri), satir("HAZIR MEVCUT", hazir)],
        "beyan": beyan, "saatlik": saatlik,
    }


# ---------------------------------------------------------------- Excel

def excel(gunler, kisiler, birim=None):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, Side
    from openpyxl.worksheet.page import PageMargins

    ata = atamalar(kisiler)
    ince, kalin = Side(style="thin"), Side(style="medium")
    cerceve = Border(left=ince, right=ince, top=ince, bottom=ince)
    yazi = "Times New Roman"
    orta = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sol = Alignment(horizontal="left", vertical="center", wrap_text=True)

    def kutu(ws, aralik, deger=None, font=None, hiza=orta):
        ilk = aralik.split(":")[0]
        if ":" in aralik:
            ws.merge_cells(aralik)
        hucre = ws[ilk]
        if deger is not None:
            hucre.value = deger
        hucre.font = font or Font(name=yazi, size=11)
        hucre.alignment = hiza
        for satir in ws[aralik] if ":" in aralik else [[hucre]]:
            for c in satir:
                c.border = cerceve
        return hucre

    def dis_cerceve(ws, ilk_satir, son_satir, ilk_sutun=1, son_sutun=10):
        for r in range(ilk_satir, son_satir + 1):
            for c in range(ilk_sutun, son_sutun + 1):
                h = ws.cell(row=r, column=c)
                b = h.border
                h.border = Border(left=kalin if c == ilk_sutun else b.left, right=kalin if c == son_sutun else b.right,
                                  top=kalin if r == ilk_satir else b.top, bottom=kalin if r == son_satir else b.bottom)

    wb = Workbook()
    wb.remove(wb.active)
    for tarih in gunler:
        v = gunluk(tarih, kisiler, birim, ata)
        ws = wb.create_sheet(f"{tarih:%d.%m.%Y}")
        for harf, en in zip("ABCDEFGHIJ", [2, 17, 13, 26, 12, 13, 17, 17, 13, 13]):
            ws.column_dimensions[harf].width = en
        kalin_yazi = Font(name=yazi, size=11, bold=True)
        baslik_yazi = Font(name=yazi, size=10, bold=True)
        veri_yazi = Font(name=yazi, size=10)

        ws.merge_cells("A1:J1")
        ws["A1"] = "\n".join(v["ust_baslik"])
        ws["A1"].font = Font(name=yazi, size=12)
        ws["A1"].alignment = orta
        ws.row_dimensions[1].height = 70
        ws.merge_cells("A2:H2")
        ws["A2"] = v["baslik"]
        ws["A2"].font = Font(name=yazi, size=12, bold=True)
        ws["A2"].alignment = orta
        ws.merge_cells("I2:J2")
        ws["I2"] = f"{tarih:%d.%m.%Y}"
        ws["I2"].font = Font(name=yazi, size=12, bold=True)
        ws["I2"].alignment = Alignment(horizontal="right", vertical="center")
        ws.row_dimensions[2].height = 24

        # sayım tablosu (3–7)
        kutu(ws, "A3:B4", "")
        kutu(ws, "C3:C4", "GENERAL\nAMİRAL", baslik_yazi)
        kutu(ws, "D3:D4", "ÖĞRETİM ELEMANI\n(SİVİL)", baslik_yazi)
        kutu(ws, "E3:F3", "ÖĞRETİM ELEMANI", baslik_yazi)
        kutu(ws, "E4", "SUBAY", baslik_yazi)
        kutu(ws, "F4", "ASTSUBAY", baslik_yazi)
        kutu(ws, "G3:G4", "SUBAY\n(YD.SB.DAHİL)", baslik_yazi)
        kutu(ws, "H3:H4", "ASB.\n(YD.ASB.DAHİL)", baslik_yazi)
        kutu(ws, "I3:I4", "SVL.ME.", baslik_yazi)
        kutu(ws, "J3:J4", "GENEL\nTOPLAM", baslik_yazi)
        ws.row_dimensions[3].height = 24
        ws.row_dimensions[4].height = 30
        for i, s in enumerate(v["sayim"]):
            r = 5 + i
            kutu(ws, f"A{r}:B{r}", s["ad"], kalin_yazi, Alignment(horizontal="left", vertical="center", indent=0))
            for j, deger in enumerate(s["degerler"]):
                kutu(ws, f"{'CDEFGHIJ'[j]}{r}", deger, kalin_yazi if j == 7 else None)
            ws.row_dimensions[r].height = 30
        dis_cerceve(ws, 3, 7)

        # gayri mevcut beyanı (9–)
        ws.merge_cells("B9:J9")
        try:
            from openpyxl.cell.rich_text import CellRichText, TextBlock
            from openpyxl.cell.text import InlineFont

            ws["B9"] = CellRichText(
                TextBlock(InlineFont(rFont=yazi, sz=11, b=True), "GAYRİ MEVCUT BEYANI ("),
                TextBlock(InlineFont(rFont=yazi, sz=11, b=True, u="single"),
                          "SADECE MESAİDE BULUNMAYAN PERSONEL BİLDİRİLECEKTİR."),
                TextBlock(InlineFont(rFont=yazi, sz=11, b=True), ")"))
        except ImportError:  # eski openpyxl
            ws["B9"] = "GAYRİ MEVCUT BEYANI (SADECE MESAİDE BULUNMAYAN PERSONEL BİLDİRİLECEKTİR.)"
            ws["B9"].font = kalin_yazi
        ws["B9"].alignment = orta
        for c in ws["B9:J9"][0]:
            c.border = cerceve
        ws.row_dimensions[9].height = 28
        for aralik, metin in (("B10", "S.NO."), ("C10:D10", "PERSONEL KİMLİĞİ"), ("E10:F10", "GÖREVİ"),
                              ("G10:H10", "MAZERET SEBEBİ"), ("I10", "AYRILIŞ\nTARİHİ"), ("J10", "KATILIŞ\nTARİHİ")):
            kutu(ws, aralik, metin, Font(name=yazi, size=10))
        ws.row_dimensions[10].height = 30
        satir_sayisi = max(EN_AZ_BEYAN_SATIRI, len(v["beyan"]))
        for i in range(satir_sayisi):
            r = 11 + i
            b = v["beyan"][i] if i < len(v["beyan"]) else None
            kutu(ws, f"B{r}", i + 1, veri_yazi)
            kutu(ws, f"C{r}:D{r}", b["kimlik"] if b else "", veri_yazi, sol)
            kutu(ws, f"E{r}:F{r}", b["gorev"] if b else "", veri_yazi, sol)
            kutu(ws, f"G{r}:H{r}", b["sebep"] if b else "", veri_yazi)
            kutu(ws, f"I{r}", b["ayrilis"] if b else "", veri_yazi)
            kutu(ws, f"J{r}", b["katilis"] if b else "", veri_yazi)
            uzun = b and (len(b["kimlik"]) > 46 or len(b["gorev"]) > 32 or len(b["katilis"]) > 10)
            ws.row_dimensions[r].height = 30 if uzun else 20
        dis_cerceve(ws, 9, 10 + satir_sayisi, 2, 10)

        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.orientation = "portrait"
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5)
        ws.print_options.horizontalCentered = True
        ws.print_area = f"A1:J{10 + satir_sayisi}"
        ws.sheet_view.showGridLines = False

    cevap = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ad = f"personel_yoklamasi_{gunler[0]:%Y%m%d}" + (f"-{gunler[-1]:%Y%m%d}" if len(gunler) > 1 else "")
    kod = getattr(getattr(birim, "bolum", None), "kod", None) or (f"birim{birim.pk}" if birim is not None else "")
    if kod:
        ad += f"_{kod}"
    cevap["Content-Disposition"] = f'attachment; filename="{ad}.xlsx"'
    wb.save(cevap)
    return cevap


def gun_listesi(bas, bit):
    if bit < bas:
        bas, bit = bit, bas
    bit = min(bit, bas + datetime.timedelta(days=EN_COK_GUN - 1))
    return [bas + datetime.timedelta(days=i) for i in range((bit - bas).days + 1)]
