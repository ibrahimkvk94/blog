"""Yıllık izin dökümü: personelin bir takvim yılında hangi izin türünü kaç kez, kaç gün (saatlikte kaç saat)
kullandığı. Ekranda önizleme ve PDF (A4 yatay). Yalnız tüm okulu yöneten hesaplar (idari işler yetkilisi, sistem
yöneticileri) alır. Bilgi amaçlı türler (ör. garnizon terk) dökümde yoktur; günler yoklamadaki gibi takvim günüdür."""

import datetime
from collections import defaultdict
from io import BytesIO
from xml.sax.saxutils import escape

from django.utils import timezone

from personel.kart import yetki_sirali

from . import servis
from .birim import BIRIMSIZ
from .models import IzinTuru, YoklamaKaydi


def _tur_sirasi(t):
    return (t.rapor_sirasi or 10 ** 4, t.sira, t.ad)


def _saat(x):
    return f"{x:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def hazirla(y, yil, birim=None, yalniz_kullanan=False):
    """{yil, birim, turler, gruplar: [(birim, [satir])], ozet: [{tur, kisi, adet, gun, saat}], kisi, kullanan}.
    satir: {p, hucre: {tur_id: {adet, gun, saat, hak, kalan, asim}}, gun, adet, saat}."""
    kisiler = list(servis.personeller(y, birim))
    yb = servis.gun_araligi(datetime.date(yil, 1, 1))[0]
    ys = servis.gun_araligi(datetime.date(yil, 12, 31))[1]
    kayitlar = defaultdict(list)
    for k in (YoklamaKaydi.objects.filter(personel__in=[p.pk for p in kisiler], baslangic__lt=ys, bitis__gt=yb)
              .exclude(tur__mevcut_sayilir=True).select_related("tur")):
        kayitlar[k.personel_id].append(k)

    satirlar, kullanilan_turler = [], set()
    for p in kisiler:
        hucre = {}
        for o in servis.yil_ozeti(kayitlar.get(p.pk, []), yil):
            if o["tur"].mevcut_sayilir:
                continue
            hucre[o["tur"].pk] = o
            if o["adet"]:
                kullanilan_turler.add(o["tur"].pk)
        dolu = [o for o in hucre.values() if o["adet"]]
        gorev = p.kadro_gorevi
        satir = {"p": p, "gorev": gorev if gorev and gorev not in p.kunye else "", "hucre": hucre, "gun": sum(o["gun"] for o in dolu), "adet": sum(o["adet"] for o in dolu),
                 "saat": sum(o["saat"] for o in dolu)}
        if satir["adet"] or not yalniz_kullanan:
            satirlar.append(satir)

    turler = sorted((t for t in IzinTuru.objects.filter(mevcut_sayilir=False)
                     if t.pk in kullanilan_turler or (t.aktif and t.yillik_hak is not None)), key=_tur_sirasi)

    for s in satirlar:  # ekran önizlemesi: türler sırasıyla (ana metin, alt metin, aşım, kullanıldı)
        s["hucreler"] = [(*hucre_metni(s["hucre"].get(t.pk)), bool((s["hucre"].get(t.pk) or {}).get("asim")),
                          bool((s["hucre"].get(t.pk) or {}).get("adet"))) for t in turler]

    # teşkilat sırasıyla birimler; birimde en yetkili başta, sonra alfabetik
    agac = y.agac
    sira = {b.pk: i for i, (b, _d) in enumerate(agac.sirali())}
    by = defaultdict(list)
    for s in satirlar:
        by[agac.kisi_birimi(s["p"])].append(s)
    gruplar = []
    for bid in sorted(by, key=lambda b: (b == 0, sira.get(b, 10 ** 6))):
        b = agac.get(bid) if bid else BIRIMSIZ
        liste = {s["p"].pk: s for s in by[bid]}
        sirali = yetki_sirali(sorted((s["p"] for s in by[bid]), key=lambda p: p.ad_soyad), b if bid else None)
        gruplar.append((b, [liste[p.pk] for p in sirali]))

    ozet = []
    for t in turler:
        hucreler = [s["hucre"].get(t.pk) for s in satirlar]
        hucreler = [h for h in hucreler if h and h["adet"]]
        ozet.append({"tur": t, "kisi": len(hucreler), "adet": sum(h["adet"] for h in hucreler),
                     "gun": sum(h["gun"] for h in hucreler), "saat": sum(h["saat"] for h in hucreler)})
    return {"yil": yil, "birim": birim, "turler": turler, "gruplar": gruplar, "ozet": ozet,
            "kisi": len(satirlar), "kullanan": sum(1 for s in satirlar if s["adet"]),
            "zaman": timezone.localtime()}


def hucre_metni(h, saat_ayri=True):
    """(ana metin, alt metin) — ör. ("5 / 30 gün", "2 kez"); kullanılmamışsa ("–", "")."""
    if not h or not h["adet"]:
        if h and h.get("hak") is not None:
            return f"0 / {h['hak']} gün", ""
        return "–", ""
    parcalar = []
    if h["gun"] or not h["saat"]:
        parcalar.append(f"{h['gun']} / {h['hak']} gün" if h.get("hak") is not None else f"{h['gun']} gün")
    if h["saat"]:
        parcalar.append(f"{_saat(h['saat'])} saat")
    return " + ".join(parcalar), f"{h['adet']} kez"


# ---------------------------------------------------------------- PDF

def pdf(veri):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from timetable.report_pdf import BOLD, FONT  # DejaVu Sans (Türkçe karakterler) burada kaydedilir

    LACIVERT, ALTIN, CIZGI = colors.HexColor("#14294A"), colors.HexColor("#C9A227"), colors.HexColor("#B9BFCA")
    BASLIK = ParagraphStyle("b", fontName=BOLD, fontSize=14, leading=17, alignment=1, textColor=LACIVERT)
    BILGI = ParagraphStyle("i", fontName=FONT, fontSize=8, leading=10.5, alignment=1, textColor=colors.HexColor("#4B5563"))
    HUCRE = ParagraphStyle("h", fontName=FONT, fontSize=7.4, leading=9, alignment=1)
    AD = ParagraphStyle("a", fontName=FONT, fontSize=7.6, leading=9.2)
    UST = ParagraphStyle("u", fontName=BOLD, fontSize=7.4, leading=9, alignment=1, textColor=colors.white)
    GRUP = ParagraphStyle("g", fontName=BOLD, fontSize=8, leading=10, textColor=LACIVERT)

    tampon = BytesIO()
    genislik = landscape(A4)[0] - 20 * mm
    turler = veri["turler"]
    sabit = [9 * mm, 74 * mm, 22 * mm]
    tur_g = (genislik - sum(sabit)) / max(1, len(turler))
    kolonlar = [sabit[0], sabit[1]] + [tur_g] * len(turler) + [sabit[2]]

    def p(metin, stil=HUCRE):
        return Paragraph(metin, stil)

    def hucre(h):
        ana, alt = hucre_metni(h)
        if ana == "–":
            return p('<font color="#9CA3AF">–</font>')
        renk = "#B91C1C" if h and h.get("asim") else ("#111827" if h and h["adet"] else "#9CA3AF")
        return p(f'<font color="{renk}"><b>{escape(ana)}</b></font>' + (f'<br/><font size="6.4" color="#6B7280">{alt}</font>' if alt else ""))

    ust = [p("S.No", UST), p("Personel", ParagraphStyle("ua", parent=UST, alignment=0))] + \
          [p(escape(t.ad) + (f'<br/><font size="6">yıllık hak {t.yillik_hak} gün</font>' if t.yillik_hak is not None else ""), UST)
           for t in turler] + [p("Toplam", UST)]
    satirlar, stil = [ust], [
        ("BACKGROUND", (0, 0), (-1, 0), LACIVERT), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ALTIN),
        ("GRID", (0, 0), (-1, -1), 0.35, CIZGI), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    no = 0
    for b, liste in veri["gruplar"]:
        r = len(satirlar)
        satirlar.append([p(f"{escape(b.ad)} <font color='#6B7280' size='7'>· {len(liste)} kişi</font>", GRUP)] + [""] * (len(kolonlar) - 1))
        stil += [("SPAN", (0, r), (-1, r)), ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#E8EDF5"))]
        for s in liste:
            no += 1
            kisi = s["p"]
            gorev = s["gorev"]
            ad = f"<b>{escape(kisi.ad_soyad)}</b> <font color='#4B5563'>{escape(kisi.kunye)}</font>" + (
                f"<br/><font size='6.4' color='#6B7280'>{escape(gorev)}</font>" if gorev else "")
            toplam = p(f"<b>{s['gun']} gün</b>" + (f" + {_saat(s['saat'])} sa" if s["saat"] else "")
                       + f"<br/><font size='6.4' color='#6B7280'>{s['adet']} kez</font>") if s["adet"] else p('<font color="#9CA3AF">–</font>')
            satirlar.append([p(str(no)), p(ad, AD)] + [hucre(s["hucre"].get(t.pk)) for t in turler] + [toplam])
            if no % 2 == 0:
                stil.append(("BACKGROUND", (0, len(satirlar) - 1), (-1, len(satirlar) - 1), colors.HexColor("#F8FAFC")))
    if no == 0:
        satirlar.append([p("Kayıt yok.")] + [""] * (len(kolonlar) - 1))
        stil.append(("SPAN", (0, 1), (-1, 1)))
    tablo = Table(satirlar, colWidths=kolonlar, repeatRows=1)
    tablo.setStyle(TableStyle(stil))

    # tür bazında özet
    oz = [[p("İzin türü", UST), p("Kullanan kişi", UST), p("Kez", UST), p("Gün", UST), p("Saat", UST)]]
    for o in veri["ozet"]:
        oz.append([p(f"<b>{escape(o['tur'].ad)}</b>", AD), p(str(o["kisi"])), p(str(o["adet"])), p(str(o["gun"])),
                   p(_saat(o["saat"]) if o["saat"] else "–")])
    ozet = Table(oz, colWidths=[60 * mm, 28 * mm, 20 * mm, 20 * mm, 20 * mm], repeatRows=1, hAlign="LEFT")
    ozet.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LACIVERT), ("LINEBELOW", (0, 0), (-1, 0), 1.2, ALTIN),
                              ("GRID", (0, 0), (-1, -1), 0.35, CIZGI), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

    kapsam = veri["birim"].ad if veri["birim"] is not None else "Tüm okul"
    zaman = veri["zaman"].strftime("%d.%m.%Y %H:%M")

    def sayfa(c, d):
        c.saveState()
        c.setFont(FONT, 7)
        c.setFillColor(colors.HexColor("#6B7280"))
        c.drawString(10 * mm, 6 * mm, f"KAMYOSİS · {veri['yil']} izin dökümü · {kapsam} · {zaman}")
        c.drawRightString(landscape(A4)[0] - 10 * mm, 6 * mm, f"Sayfa {d.page}")
        c.setStrokeColor(ALTIN)
        c.setLineWidth(1.2)
        c.line(10 * mm, landscape(A4)[1] - 8 * mm, landscape(A4)[0] - 10 * mm, landscape(A4)[1] - 8 * mm)
        c.restoreState()

    doc = SimpleDocTemplate(tampon, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
                            topMargin=11 * mm, bottomMargin=11 * mm, title=f"{veri['yil']} izin dökümü",
                            author="KAMYOSİS")
    hikaye = [
        Paragraph(f"{veri['yil']} Yılı Personel İzin Kullanım Dökümü", BASLIK),
        Paragraph(f"{escape(kapsam)} · {veri['kisi']} personel, {veri['kullanan']} kişi izin kullandı · düzenlenme {zaman}", BILGI),
        Paragraph("Tam gün kayıtları yıla düşen takvim günüyle, saatlik kayıtlar saatle sayılır; “kez” kayıt sayısıdır. "
                  "Yıllık hakkı olan türlerde kullanılan / hak gösterilir, aşım kırmızıdır. Bilgi amaçlı türler (ör. garnizon "
                  "terk) dökümde yoktur.", BILGI),
        Spacer(1, 4 * mm), tablo, Spacer(1, 6 * mm),
        Paragraph("Tür bazında özet", ParagraphStyle("os", parent=GRUP, fontSize=9.5, spaceAfter=3)), ozet,
    ]
    doc.build(hikaye, onFirstPage=sayfa, onLaterPages=sayfa)
    return tampon.getvalue()
