"""Personel kartı için rütbe, sınıf ve akademik unvan işaretleri (sade vektör çizimler, dosya gerekmez).

Subay: apolet (yıldız; binbaşı-albay defne çelenk; generaller kırmızı zeminli çelenk ve kılıçlar; asteğmen şerit).
Astsubay: ay-yıldızlı kol işareti (çavuştan kıdemli üstçavuşa 1–4 şerit; başçavuşlarda kare zemin ve alt çizgi).
Sınıf: yaka işareti (sınıfın kumaş rengi ve amblemi). Akademik unvan: kep; doktor öğretim üyesi, doçent ve
profesör için 1, 2, 3 altın şerit.
"""

import math

from django.utils.html import escape
from django.utils.safestring import mark_safe

ALTIN, KOYU = "#d9ac2f", "#8a6a12"


def _yildiz(cx, cy, r):
    nokta = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r * 0.42 if i % 2 else r
        nokta.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    return f'<polygon points="{" ".join(nokta)}" fill="{ALTIN}" stroke="{KOYU}" stroke-width=".6"/>'


def _celenk(cx, cy, merkez):
    """İki defne dalı alttan yukarı oval merkezi sarar."""
    s = []
    for i in range(6):
        a = math.radians(105 + i * 24)  # sol dal: alttan sol üste
        for yon in (-1, 1):
            aa = a if yon < 0 else math.pi - a
            x, y = cx + 12.5 * math.cos(aa), cy + 10 * math.sin(aa)
            aci = math.degrees(aa) + 90
            s.append(f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="4.2" ry="1.9" transform="rotate({aci:.0f} {x:.1f} {y:.1f})" '
                     f'fill="{ALTIN}" stroke="{KOYU}" stroke-width=".4"/>')
    s.append(f'<ellipse cx="{cx}" cy="{cy}" rx="7.5" ry="6.5" fill="{merkez}" stroke="{ALTIN}" stroke-width="1.6"/>')
    return "".join(s)


# rütbe: (yıldız, tür) — tür 0 yalın, 1 çelenk (üst rütbe), 2 general, 3 asteğmen şeridi
SUBAY = {"Asteğmen": (0, 3), "Atğm.": (0, 3), "Tğm.": (1, 0), "Ütğm.": (2, 0), "Kd.Ütğm.": (2, 0), "Yzb.": (3, 0),
         "Bnb.": (1, 1), "Yb.": (2, 1), "Alb.": (3, 1), "Tuğg.": (1, 2), "Tümg.": (2, 2), "Korg.": (3, 2),
         "Org.": (4, 2)}
SUBAY_ADI = {"Asteğmen": "Asteğmen", "Atğm.": "Asteğmen", "Tğm.": "Teğmen", "Ütğm.": "Üsteğmen",
             "Kd.Ütğm.": "Kıdemli Üsteğmen", "Yzb.": "Yüzbaşı", "Bnb.": "Binbaşı", "Yb.": "Yarbay", "Alb.": "Albay",
             "Tuğg.": "Tuğgeneral", "Tümg.": "Tümgeneral", "Korg.": "Korgeneral", "Org.": "Orgeneral"}


def apolet(rutbe):
    n, tur = SUBAY[rutbe]
    s = [f'<path d="M6 30 Q6 4 24 4 Q42 4 42 30 L42 118 L6 118 Z" fill="#3a4630" stroke="#262e1f"/>',
         f'<circle cx="24" cy="15" r="5.5" fill="{ALTIN}" stroke="{KOYU}"/>']
    if tur == 3:
        s.append(f'<rect x="13" y="96" width="22" height="7" rx="1" fill="{ALTIN}"/>')
    taban = 82 if tur in (1, 2) else 104
    aralik = 11 if n > 3 else 15
    for i in range(n):
        s.append(_yildiz(24, max(36, taban - 16 - i * aralik), 5.6))
    if tur == 1:
        s.append(_celenk(24, 100, "#1b8a8a"))
    elif tur == 2:
        s.append(_celenk(24, 100, "#c0262d"))
        s.append('<path d="M18 94 L30 106 M30 94 L18 106" stroke="#fff" stroke-width="1.2"/>')
    return f'<svg viewBox="0 0 48 122" width="48" height="122" aria-hidden="true">{"".join(s)}</svg>'


# astsubay: (şerit, alt çizgi, kare zemin)
ASTSUBAY = {"Asb.Astçvş.": (0, 1, False), "Asb.Çvş.": (1, 0, False), "Asb.Kd.Çvş.": (2, 0, False),
            "Asb.Üçvş.": (3, 0, False), "Asb.Kd.Üçvş.": (4, 0, False), "Asb.Bçvş.": (4, 1, True),
            "Asb.Kd.Bçvş.": (4, 2, True)}
ASTSUBAY_ADI = {"Asb.Astçvş.": "Astsubay Astçavuş", "Asb.Çvş.": "Astsubay Çavuş", "Asb.Kd.Çvş.": "Astsubay Kd. Çavuş",
                "Asb.Üçvş.": "Astsubay Üstçavuş", "Asb.Kd.Üçvş.": "Astsubay Kd. Üstçavuş",
                "Asb.Bçvş.": "Astsubay Başçavuş", "Asb.Kd.Bçvş.": "Astsubay Kd. Başçavuş"}


def kol_isareti(rutbe):
    serit, cizgi, kare = ASTSUBAY[rutbe]
    s = ['<rect x="2" y="2" width="68" height="70" rx="3" fill="#161616"/>' if kare else
         '<path d="M2 4 L36 18 L70 4 L70 44 L36 68 L2 44 Z" fill="#161616"/>']
    for i in range(serit):  # şeritler ay-yıldızı içten dışa sarar
        y = 30 + i * 7
        s.append(f'<path d="M9 {y - 14} L36 {y + 4} L63 {y - 14}" fill="none" stroke="{ALTIN}" '
                 f'stroke-width="4" stroke-linecap="round"/>')
    s.append(f'<path d="M30 16 A7 7 0 1 0 42 16 A5.5 5.5 0 1 1 30 16" fill="{ALTIN}"/>')
    s.append(_yildiz(36, 13, 3.2))
    for i in range(cizgi):
        s.append(f'<rect x="10" y="{54 + i * 7 if kare else 46 + i * 7}" width="52" height="4" rx="1" fill="{ALTIN}"/>')
    return f'<svg viewBox="0 0 72 74" width="72" height="74" aria-hidden="true">{"".join(s)}</svg>'


def _g(icerik, kalinlik=1.8):
    return (f'<g fill="none" stroke="{ALTIN}" stroke-width="{kalinlik}" stroke-linecap="round" '
            f'stroke-linejoin="round">{icerik}</g>')


def _disli(cx, cy, r, dis):
    s = f'<circle cx="{cx}" cy="{cy}" r="{r}"/><circle cx="{cx}" cy="{cy}" r="{r * .38:.1f}" fill="{ALTIN}"/>'
    for i in range(dis):
        a = i * 2 * math.pi / dis
        s += (f'<path d="M{cx + r * math.cos(a):.1f} {cy + r * math.sin(a):.1f} L{cx + (r + 4) * math.cos(a):.1f} '
              f'{cy + (r + 4) * math.sin(a):.1f}" stroke-width="3.4"/>')
    return s


_BASAK = "".join(
    f'<ellipse cx="20" cy="{42 + i * 6}" rx="4" ry="2.2" transform="rotate(-35 20 {42 + i * 6})" fill="{ALTIN}" stroke="none"/>'
    f'<ellipse cx="28" cy="{42 + i * 6}" rx="4" ry="2.2" transform="rotate(35 28 {42 + i * 6})" fill="{ALTIN}" stroke="none"/>'
    for i in range(5))
_ASA = ('<path d="M24 34 L24 72" stroke-width="2.6"/>'
        '<path d="M27 38 Q31 41 26 44 Q16 48 24 53 Q32 57 22 62 Q17 65 22 68" stroke-width="1.9"/>')

# sınıf kısaltması: (ad, kumaş rengi, amblem)
SINIF = {
    "Öğ.": ("Öğretmen", "#3d8b4a", _g(
        f'<path d="M12 60 Q18 56 24 60 Q30 56 36 60 L36 70 Q30 66 24 70 Q18 66 12 70 Z" fill="{ALTIN}"/>'
        f'<path d="M24 40 L24 58"/><path d="M24 34 Q19 40 24 44 Q29 40 24 34" fill="{ALTIN}"/>'
        '<path d="M15 48 Q12 56 16 62 M33 48 Q36 56 32 62"/>')),
    "Müh.": ("Mühendis", "#78b9d3", _g(
        f'<path d="M24 36 L14 70 M24 36 L34 70 M17 58 L31 58"/><circle cx="24" cy="36" r="2.5" fill="{ALTIN}"/>'
        '<path d="M12 72 L36 72" stroke-width="2.4"/>')),
    "Topçu": ("Topçu", "#2f4a78", _g(
        '<path d="M13 40 L35 66 M35 40 L13 66" stroke-width="3"/><circle cx="16" cy="64" r="3.5"/>'
        '<circle cx="32" cy="64" r="3.5"/>')),
    "P.": ("Piyade", "#1f6b4f", _g('<path d="M14 38 L34 68 M34 38 L14 68" stroke-width="2.4"/>'
                                    '<path d="M12 64 L18 70 M36 64 L30 70" stroke-width="3.2"/>')),
    "P.Kur.": ("Kurmay", "#7d2f45", ""),
    "İkm.": ("İkmal", "#b4a9d0", _g('<path d="M24 36 L24 72"/>' + _BASAK)),
    "Tnk.": ("Tank", "#868b90", _g(
        f'<rect x="11" y="56" width="26" height="9" rx="4.5" fill="{ALTIN}"/>'
        f'<path d="M16 56 L18 49 L30 49 L32 56" fill="{ALTIN}"/><path d="M27 51 L39 47" stroke-width="2.4"/>')),
    "Bkm.": ("Bakım", "#262626", _g(_disli(24, 54, 9, 8))),
    "Tbp.": ("Tabip", "#74283a", _g(_ASA)),
    "Sağ.": ("Sağlık", "#74283a", _g(_ASA)),
    "Vet.": ("Veteriner hekim", "#74283a", _g(_ASA)),
    "Mu.": ("Muhabere", "#1c2c6b", _g('<path d="M14 40 L24 56 L34 40 M24 56 L24 72"/><path d="M18 64 L30 64"/>'
                                       '<path d="M20 34 L28 34"/>')),
    "Hv.Svn.": ("Hava savunma", "#2f4a78", _g(
        f'<path d="M24 34 L28 44 L28 62 L20 62 L20 44 Z" fill="{ALTIN}"/><path d="M20 56 L15 64 M28 56 L33 64"/>'
        '<path d="M12 70 Q24 62 36 70"/>')),
    "U/H Tekns.": ("Uçak ve helikopter teknisyeni", "#8db8d6", _g(
        _disli(24, 54, 8, 10) + '<path d="M24 54 L24 40 M24 54 L36 60 M24 54 L12 60" stroke-width="2.2"/>')),
    "İs.": ("İstihkam", "#1c2c6b", _g(
        f'<path d="M13 70 L13 50 L17 50 L17 46 L21 46 L21 50 L27 50 L27 46 L31 46 L31 50 L35 50 L35 70 Z" fill="{ALTIN}"/>'
        '<path d="M21 70 L21 62 Q24 58 27 62 L27 70" stroke="#1c2c6b" stroke-width="1.6"/>')),
    "Ulş.": ("Ulaştırma", "#1c2c6b", _g(_disli(24, 54, 8, 8) + '<path d="M10 54 L38 54"/>')),
    "Mly.": ("Maliye", "#78b9d3", _g('<path d="M24 38 L35 54 L24 70 L13 54 Z"/><path d="M24 44 L31 54 L24 64 L17 54 Z"/>')),
    "Per.": ("Personel", "#262626", _g(f'<path d="M24 36 Q17 46 24 56 Q31 46 24 36" fill="{ALTIN}"/>'
                                       '<path d="M24 56 L24 70 M18 70 L30 70"/>')),
    "Bnd.": ("Bando", "#6e3d8a", _g('<path d="M16 40 Q14 60 24 70 Q34 60 32 40"/><path d="M19 46 L19 64 M24 44 L24 68 M29 46 L29 64"/>')),
}

AKADEMIK = {"Dr.": ("Doktor", 0), "Öğt.Gör.Dr.": ("Doktor öğretim görevlisi", 0),
            "Dr.Öğt.Üyesi": ("Doktor öğretim üyesi", 1), "Doç.Dr.": ("Doçent", 2), "Prof.Dr.": ("Profesör", 3)}


def yaka(sinif):
    _, renk, amblem = SINIF[sinif]
    return (f'<svg viewBox="0 0 48 80" width="48" height="80" aria-hidden="true">'
            f'<path d="M4 20 L24 4 L44 20 L44 78 L4 78 Z" fill="{renk}" stroke="rgba(0,0,0,.35)"/>'
            f'<circle cx="24" cy="20" r="5.5" fill="{ALTIN}" stroke="{KOYU}"/>{amblem}</svg>')


def kep(serit):
    s = ['<path d="M8 4 L56 4 L56 64 Q32 80 8 64 Z" fill="#14294a" stroke="#c9a227" stroke-width="2"/>',
         f'<path d="M14 26 L32 17 L50 26 L32 35 Z" fill="{ALTIN}" stroke="{KOYU}" stroke-width=".8"/>',
         f'<path d="M21 30 L21 39 Q32 45 43 39 L43 30 L32 35 Z" fill="{ALTIN}" stroke="{KOYU}" stroke-width=".8"/>',
         f'<path d="M50 26 L50 38" stroke="{ALTIN}" stroke-width="1.6"/><circle cx="50" cy="40" r="2" fill="{ALTIN}"/>']
    for i in range(serit):
        s.append(f'<rect x="18" y="{50 + i * 6}" width="28" height="3.4" rx="1" fill="{ALTIN}"/>')
    return f'<svg viewBox="0 0 64 80" width="64" height="80" aria-hidden="true">{"".join(s)}</svg>'


# sivil personel: gömlek ve kravat (Devlet memuru / VHKİ: Veri Hazırlama Kontrol İşletmeni)
SIVIL = {"De.Me": ("Devlet memuru", "#f8fafc", "#1f3a5f"), "VHK": ("VHKİ", "#cfe3f5", "#7d2f45")}


def gomlek(gomlek_rengi, kravat_rengi):
    return ('<svg viewBox="0 0 64 70" width="58" height="64" aria-hidden="true">'
            f'<path d="M8 22 L22 10 L32 16 L42 10 L56 22 L56 66 L8 66 Z" fill="{gomlek_rengi}" stroke="#94a3b8" stroke-width="1.2"/>'
            '<path d="M22 10 L32 16 L42 10" fill="none" stroke="#94a3b8" stroke-width="1.2"/>'
            f'<path d="M22 10 L27 24 L32 16 Z M42 10 L37 24 L32 16 Z" fill="{gomlek_rengi}" stroke="#64748b" stroke-width="1.2" stroke-linejoin="round"/>'
            f'<path d="M29 17 L35 17 L34 23 L30 23 Z" fill="{kravat_rengi}"/>'
            f'<path d="M30 23 L34 23 L37 52 L32 59 L27 52 Z" fill="{kravat_rengi}"/>'
            '<path d="M30.5 30 L35 34 M29.5 38 L35.5 43" stroke="rgba(255,255,255,.35)" stroke-width="1.6"/>'
            '</svg>')


def baskan_nisani():
    """Bölüm başkanı: kırmızı zeminde güneş ve yıldız halkası, altın çerçeve; altta lacivert-altın kurdele."""
    s = ['<svg viewBox="0 0 80 96" width="66" height="80" aria-hidden="true">',
         f'<path d="M26 60 L18 94 L30 86 L36 94 L40 64 Z" fill="#1f3a5f" stroke="{ALTIN}" stroke-width="1.2"/>',
         f'<path d="M54 60 L62 94 L50 86 L44 94 L40 64 Z" fill="#1f3a5f" stroke="{ALTIN}" stroke-width="1.2"/>',
         f'<circle cx="40" cy="38" r="34" fill="{ALTIN}" stroke="{KOYU}" stroke-width="1.2"/>',
         '<circle cx="40" cy="38" r="29" fill="#a3161f" stroke="#7a0f16" stroke-width="1"/>']
    for i in range(12):  # güneş ışınları
        a = i * math.pi / 6
        x1, y1 = 40 + 7 * math.cos(a - .16), 38 + 7 * math.sin(a - .16)
        x2, y2 = 40 + 7 * math.cos(a + .16), 38 + 7 * math.sin(a + .16)
        xu, yu = 40 + 15 * math.cos(a), 38 + 15 * math.sin(a)
        s.append(f'<polygon points="{x1:.1f},{y1:.1f} {xu:.1f},{yu:.1f} {x2:.1f},{y2:.1f}" fill="{ALTIN}"/>')
    s.append(f'<circle cx="40" cy="38" r="7.5" fill="{ALTIN}" stroke="{KOYU}" stroke-width=".8"/>')
    for i in range(8):  # yıldız halkası
        a = -math.pi / 2 + i * math.pi / 4 + math.pi / 8
        s.append(_yildiz(40 + 22 * math.cos(a), 38 + 22 * math.sin(a), 3.4))
    s.append("</svg>")
    return "".join(s)


def idari_nisan(no=1):
    """İdari kadro: sekiz köşeli altın nişan, lacivert mineli merkez; ağır, ara sıra geçen bir parıltı."""
    yildiz8, ic = [], []
    for i in range(16):
        a = -math.pi / 2 + i * math.pi / 8
        r = 34 if i % 2 == 0 else 22
        yildiz8.append(f"{40 + r * math.cos(a):.1f},{40 + r * math.sin(a):.1f}")
    for i in range(16):
        a = -math.pi / 2 + i * math.pi / 8
        r = 27 if i % 2 == 0 else 18
        ic.append(f"{40 + r * math.cos(a):.1f},{40 + r * math.sin(a):.1f}")
    nokta = " ".join(yildiz8)
    return ('<svg viewBox="0 0 80 80" width="70" height="70" aria-hidden="true" class="yk-idari-nisan">'
            f'<defs><clipPath id="ykn{no}"><polygon points="{nokta}"/></clipPath>'
            f'<linearGradient id="ykg{no}" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset=".5" stop-color="#fff" stop-opacity=".75"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>'
            '</linearGradient></defs>'
            f'<polygon points="{nokta}" fill="{ALTIN}" stroke="{KOYU}" stroke-width="1"/>'
            f'<polygon points="{" ".join(ic)}" fill="#e9c75a" stroke="{KOYU}" stroke-width=".6"/>'
            f'<circle cx="40" cy="40" r="14" fill="#1f3a5f" stroke="{ALTIN}" stroke-width="2.2"/>'
            f'<circle cx="40" cy="40" r="10.5" fill="none" stroke="{ALTIN}" stroke-width=".8" stroke-dasharray="1.6 1.6"/>'
            + _yildiz(40, 40, 6.5) +
            f'<g clip-path="url(#ykn{no})"><rect class="yk-parilti" x="-30" y="-10" width="18" height="100" '
            f'fill="url(#ykg{no})" transform="skewX(-18)"/></g></svg>')


def personel_isaretleri(p):
    """[(svg, etiket)] — kartta fotoğrafın yanında gösterilecek işaretler (yoksa boş liste)."""
    rutbe, sinif, unvan = (str(x or "").strip() for x in (p.rutbe, p.sinif, p.unvan))
    out = []
    if rutbe in SUBAY:
        out.append((apolet(rutbe), SUBAY_ADI[rutbe]))
    elif rutbe in ASTSUBAY:
        out.append((kol_isareti(rutbe), ASTSUBAY_ADI[rutbe]))
    else:
        for onek, (ad, g, k) in SIVIL.items():
            if any(x.replace(" ", "").startswith(onek) for x in (rutbe, sinif, unvan)):
                out.append((gomlek(g, k), ad))
                break
    if sinif in SINIF and rutbe:
        out.append((yaka(sinif), SINIF[sinif][0]))
    if unvan in AKADEMIK:
        ad, serit = AKADEMIK[unvan]
        out.append((kep(serit), ad))
    bolum = getattr(p, "bolum", None)
    if bolum is not None and bolum.baskan_id == p.pk:
        out.append((baskan_nisani(), "Bölüm başkanı"))
    if getattr(p, "idari_kadro", False):
        out.append((idari_nisan(p.pk), getattr(p, "gorev_unvani", "") or "İdari kadro"))
    return [(mark_safe(svg), escape(etiket)) for svg, etiket in out]
