"""Personel kartı için rütbe, sınıf ve akademik unvan işaretleri (vektör çizimler).

Subay: apolet (yıldız; binbaşı-albay defne çelenk; generaller kırmızı zeminli çelenk ve kılıçlar; asteğmen şerit).
Astsubay: orijinal TSK rütbe işaretleri (yoklama/rutbe_svg; çavuşta 2, kd. üstçavuşta 5 kıvrımlı şerit;
başçavuşlarda kare zemin ve alt çizgi).
Sınıf: yaka işareti (sınıfın kumaş rengi ve amblemi). Akademik unvan: kep; doktor öğretim üyesi, doçent ve
profesör için 1, 2, 3 altın şerit.
"""

import math
import re
from functools import lru_cache
from pathlib import Path

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


# astsubay: orijinal TSK rütbe işaretleri (yoklama/rutbe_svg, kaynak ve lisanslar KAYNAK.txt'de)
ASTSUBAY = {"Asb.Astçvş.": "astcavus", "Asb.Çvş.": "cavus", "Asb.Kd.Çvş.": "kd_cavus", "Asb.Üçvş.": "ustcavus",
            "Asb.Kd.Üçvş.": "kd_ustcavus", "Asb.Bçvş.": "bascavus", "Asb.Kd.Bçvş.": "kd_bascavus"}
ASTSUBAY_ADI = {"Asb.Astçvş.": "Astsubay Astçavuş", "Asb.Çvş.": "Astsubay Çavuş", "Asb.Kd.Çvş.": "Astsubay Kd. Çavuş",
                "Asb.Üçvş.": "Astsubay Üstçavuş", "Asb.Kd.Üçvş.": "Astsubay Kd. Üstçavuş",
                "Asb.Bçvş.": "Astsubay Başçavuş", "Asb.Kd.Bçvş.": "Astsubay Kd. Başçavuş"}
RUTBE_SVG = Path(__file__).resolve().parent / "rutbe_svg"


@lru_cache(maxsize=None)
def kol_isareti(rutbe):
    """Astsubay rütbe işareti: siyah zemin üzerinde ay-yıldızı saran kıvrımlı sarı şeritler (orijinal çizim)."""
    svg = (RUTBE_SVG / f"{ASTSUBAY[rutbe]}.svg").read_text(encoding="utf-8").strip()
    return svg.replace("<svg ", '<svg width="72" aria-hidden="true" ', 1)


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

# Öğretmen: arkada meşale (alev, kâse, sap), önde açık kitap; altın ve alev geçişleriyle gerçeğe yakın
OGRETMEN = (
    '<defs>'
    '<linearGradient id="ogS" x1="0" x2="1"><stop offset="0" stop-color="#8a6a12"/><stop offset=".5" stop-color="#f6dc85"/>'
    '<stop offset="1" stop-color="#8a6a12"/></linearGradient>'
    '<linearGradient id="ogY" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#d9480f"/>'
    '<stop offset=".45" stop-color="#f59f00"/><stop offset="1" stop-color="#ffe066"/></linearGradient>'
    '<linearGradient id="ogSol" x1="0" x2="1"><stop offset="0" stop-color="#fbe9a6"/><stop offset=".75" stop-color="#e2b93b"/>'
    '<stop offset="1" stop-color="#a87f16"/></linearGradient>'
    '<linearGradient id="ogSag" x1="1" x2="0"><stop offset="0" stop-color="#fbe9a6"/><stop offset=".75" stop-color="#e2b93b"/>'
    '<stop offset="1" stop-color="#a87f16"/></linearGradient>'
    '<radialGradient id="ogH" cx=".5" cy=".55" r=".5"><stop offset="0" stop-color="#ffe066" stop-opacity=".55"/>'
    '<stop offset="1" stop-color="#ffe066" stop-opacity="0"/></radialGradient></defs>'
    '<circle cx="24" cy="34" r="10" fill="url(#ogH)"/>'
    '<path d="M22 46.5 L26 46.5 L25.1 67 L22.9 67 Z" fill="url(#ogS)" stroke="#6b500c" stroke-width=".4"/>'
    '<path d="M22.2 50.5 L25.8 50.5 M22.4 54.5 L25.6 54.5" stroke="#6b500c" stroke-width=".7"/>'
    '<path d="M18.4 40.6 L29.6 40.6 L27.1 46.8 L20.9 46.8 Z" fill="url(#ogS)" stroke="#6b500c" stroke-width=".5"/>'
    '<path d="M20.2 43.6 L27.8 43.6" stroke="#6b500c" stroke-width=".45"/>'
    '<ellipse cx="24" cy="40.6" rx="5.6" ry="1.35" fill="#f6dc85" stroke="#6b500c" stroke-width=".4"/>'
    '<path d="M24 26.2 C25.6 29.6 30.1 31.6 29.7 36.1 C29.5 38.7 27.6 40.7 24 40.9 C20.4 40.7 18.5 38.7 18.3 36.1 '
    'C18.1 33.1 20.5 31.7 21.5 29.5 C21.9 31.6 22.7 32.5 23.6 32.7 C23.1 30.7 23.4 28.3 24 26.2 Z" fill="url(#ogY)" '
    'stroke="#c2410c" stroke-width=".35"/>'
    '<path d="M24 32.2 C25.3 34.2 27.1 35.2 26.7 37.6 C26.4 39.1 25.4 39.9 24 40 C22.6 39.9 21.6 39.1 21.4 37.6 '
    'C21.2 35.8 22.8 34.8 24 32.2 Z" fill="#fff3bf"/>'
    '<path d="M24 61.2 Q16.4 57.6 8.2 59.6 L8.2 70.8 Q16.4 69.2 24 72.8 Q31.6 69.2 39.8 70.8 L39.8 59.6 '
    'Q31.6 57.6 24 61.2 Z" fill="#7a5c0e"/>'
    '<path d="M24 59.6 Q16.8 56 9.4 58 L9.4 69 Q16.8 67.4 24 71 Z" fill="url(#ogSol)" stroke="#8a6a12" stroke-width=".45"/>'
    '<path d="M24 59.6 Q31.2 56 38.6 58 L38.6 69 Q31.2 67.4 24 71 Z" fill="url(#ogSag)" stroke="#8a6a12" stroke-width=".45"/>'
    '<path d="M11.6 60.9 Q16.6 59.2 21.6 61.4 M11.6 63.6 Q16.6 61.9 21.6 64.1 M11.6 66.3 Q16.6 64.6 21.6 66.8 '
    'M26.4 61.4 Q31.4 59.2 36.4 60.9 M26.4 64.1 Q31.4 61.9 36.4 63.6 M26.4 66.8 Q31.4 64.6 36.4 66.3" fill="none" '
    'stroke="#a07a14" stroke-width=".5"/>'
    '<path d="M24 59.6 L24 71" stroke="#6b500c" stroke-width=".9"/>'
)

# sınıf kısaltması: (ad, kumaş rengi, amblem)
SINIF = {
    "Öğ.": ("Öğretmen", "#3d8b4a", OGRETMEN),
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
SIVIL = {"De.Me": ("Devlet memuru", "#f8fafc", "#1f3a5f"),
         "Söz.De.Me": ("Sözleşmeli devlet memuru", "#f8fafc", "#1f3a5f"),
         "VHK": ("VHKİ", "#cfe3f5", "#7d2f45")}


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


# KAMYOSİS logosu (static/img/logo_beyaz.png'dan vektöre çevrildi; görüntü kutusu 10 50 300 220)
LOGO_YOLU = (
    "M305.5 56 L307 56 L306.5 64.5 L303 87.5 L300 96 L294 105.5 L284.5 115 L269 126 L250 137 L248.5 137 L"
    "248 138 L223 150 L223 176.5 L221 188 L217 200 L213 206 L213 207.5 L209 212 L208.5 214.5 L231 236.5 L"
    "232 236.5 L233 239 L207 238.5 L196 240 L179 245 L178.5 246 L170.5 249 L165 253 L163 255 L163 253 L16"
    "4 253 L168.5 248 L171 247 L171 246 L179 241 L181 241 L186.5 238 L199 235 L219 234 L219 232.5 L217 23"
    "0 L216 230 L216 229 L205 217.5 L205 215.5 L214 198.5 L218 182 L218 165.5 L217 159.5 L213 145.5 L212 "
    "145 L212 143 L210 139.5 L210 136 L214.5 133 L216 133 L222.5 128 L224 128 L228.5 124 L240 117 L241.5 "
    "115 L255 106 L255 105 L257.5 104 L274 91 L274 90 L285 81 L285 80 L286 80 L286 79 L287 79 L294 72 L29"
    "4 71 L295 71ZM12 57 L14 58 L19 66.5 L22 69 L24.5 73 L35 83 L36 83 L36 84 L49 94 L49 95 L71 112 L78 1"
    "16 L78 117 L80 117.5 L81 119 L102 133 L109 136.5 L109 140 L106 145.5 L102 160.5 L101 180.5 L105 198."
    "5 L109 207.5 L115 216.5 L115 218 L99.5 233 L99.5 234.5 L118 235 L132 238 L132.5 239 L139.5 241 L149 "
    "247 L156 253.5 L156 255 L155 254 L150 250 L142.5 247 L142 246 L122 240 L108.5 238.5 L85.5 239 L85.5 "
    "238 L87 237.5 L110.5 214 L110 211.5 L106 206.5 L106 205 L102 198.5 L97 183 L97 179 L96 177.5 L96 150"
    ".5 L75.5 141 L51 127 L45 122 L38 118 L32 113 L28 108 L27 108 L19 96 L16 88.5 L12 70ZM148 99 L158.5 1"
    "06.5 L161.5 106 L163 104 L169 100 L170.5 100 L167 111.5 L168.5 114 L175 118 L175 119 L177 119.5 L177"
    ".5 121 L165 121.5 L163 123 L160 134 L159 134 L157 126.5 L156 126 L156 123.5 L154 121 L141.5 121 L142"
    ".5 119 L145 118 L145 117 L150.5 114 L151.5 112.5ZM14.5 113.5 L16 113.5 L19.5 117 L26 121 L26 122 L46"
    " 135 L47.5 135 L51.5 138 L61.5 142 L62 143 L68.5 145 L69 146 L71 146 L71.5 147 L83.5 151 L86 153 L86"
    " 176 L88 186.5 L91 195.5 L97 206.5 L99 208.5 L99 210 L101 212 L102 216 L80 237.5 L79 237.5 L72 244.5"
    " L72 246 L80 245 L107 245 L122 247 L142.5 253 L155 261 L155 262 L149 262 L145.5 261 L112 260 L81.5 2"
    "61 L64 263 L62 264 L56 264 L56 263 L65.5 261 L77.5 258 L94 256 L125 256 L135 257 L147.5 260 L149.5 2"
    "60 L149.5 259 L145.5 258 L140.5 255 L138 255 L137.5 254 L115 250 L81.5 250 L56 252 L56 251 L100 216 "
    "L101 214 L89 195.5 L85 185.5 L82 169 L81 168 L73 167 L57 162 L56.5 161 L49 158 L47 156 L45.5 156 L36"
    " 149 L28 141 L28 140 L27 140 L21 131.5 L17 122.5 L16 117.5 L15 117ZM303 113.5 L304 113.5 L304 116 L2"
    "97 133 L291 141 L290 141 L290 142 L289 142 L289 143 L286 145 L283 149 L280.5 150 L276.5 154 L275 154"
    " L270 158 L268.5 158 L264 161 L257 163 L256.5 164 L250.5 165 L250 166 L238 168 L236.5 169.5 L234 184"
    ".5 L230 195 L225 204 L218 213.5 L218 215 L221 217 L221 218 L243 235 L243 236 L262.5 251 L262.5 252 L"
    "230 249.5 L201 250 L180 254 L168 259.5 L170.5 260 L183 257 L193 256 L224 256 L240.5 258 L251.5 260.5"
    " L262 263 L262 264 L236 261 L206 260 L191 260 L169 262 L163 262 L163 261 L168 257 L177 253 L177.5 25"
    "2 L195 247 L217.5 244.5 L246 245.5 L246 244 L244 243 L244 242 L243 242 L243 241 L242 241 L242 240 L2"
    "41 240 L241 239 L240 239 L240 238 L239 238 L239 237 L238 237 L238 236 L237 236 L237 235 L236 235 L23"
    "6 234 L235 234 L235 233 L234 233 L234 232 L233 232 L217 216 L217 213.5 L225 201 L230 189.5 L233 174 "
    "L233 152.5 L257 143 L257.5 142 L271 136 L290 124 L290 123 L294 121 L294 120 L298 118 L298 117 L302 1"
    "15ZM132 131 L132.5 132 L129 136.5 L126 145 L125.5 155 L127 163 L128 163.5 L128 165.5 L131 171 L134 1"
    "75 L137 177 L137 178 L143 182 L150 185 L153 185 L154.5 186 L164.5 186 L172 184 L182 178 L189 170 L19"
    "3 160.5 L194 150 L192 140.5 L187.5 131.5 L192 135.5 L196 141 L196 142.5 L199 147 L200 152 L201.5 158"
    ".5 L201 171.5 L197 182.5 L188 194 L181 199 L168 204 L156 204.5 L147 203 L146.5 202 L144.5 202 L138 1"
    "99 L127.5 190 L123 183.5 L119 174 L118 169 L118 157 L120 148.5 L126 136.5Z"
)

MUHURLER = {  # makam: (kenar, koyu kenar, mine, yazı/logo, metin, yıldız)
    "mudur": ("#d9ac2f", "#8a6a12", "#14294a", "#e9c75a", "YÜKSEKOKUL MÜDÜRÜ", 2),
    "yardimci": ("#c7cdd6", "#6b7380", "#14294a", "#e6eaf0", "MÜDÜR YARDIMCISI", 0),
}


def muhur(makam, no=1):
    """Resmî mühür: dişli kenar, üst yayda makam yazısı, ortada KAMYOSİS logosu. Müdürde iki yıldız
    (tümgeneral dengi), müdür yardımcısında gümüş ve yıldızsız."""
    kenar, koyu, mine, yazi, metin, yildiz_sayisi = MUHURLER[makam]
    disler = "".join(f'<circle cx="{50 + 44 * math.cos(i * math.pi / 18):.1f}" cy="{50 + 44 * math.sin(i * math.pi / 18):.1f}" '
                     f'r="4.2" fill="{kenar}"/>' for i in range(36))
    yildizlar = ""
    for i in range(yildiz_sayisi):
        x = 50 + (i - (yildiz_sayisi - 1) / 2) * 11
        yildizlar += _yildiz(x, 82, 3.6).replace(f'fill="{ALTIN}" stroke="{KOYU}"', f'fill="{yazi}" stroke="{koyu}"')
    return (f'<svg viewBox="0 0 100 100" width="76" height="76" aria-hidden="true" class="yk-muhur">'
            f'<defs><clipPath id="ykm{no}"><circle cx="50" cy="50" r="47"/></clipPath>'
            f'<path id="yky{no}" d="M17.5 50 A32.5 32.5 0 0 1 82.5 50"/>'
            f'<linearGradient id="ykmg{no}" x1="0" x2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
            '<stop offset=".5" stop-color="#fff" stop-opacity=".7"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>'
            '</linearGradient></defs>'
            f'{disler}<circle cx="50" cy="50" r="44" fill="{kenar}" stroke="{koyu}" stroke-width=".6"/>'
            f'<circle cx="50" cy="50" r="40" fill="{mine}" stroke="{kenar}" stroke-width="2"/>'
            f'<circle cx="50" cy="50" r="24.5" fill="none" stroke="{yazi}" stroke-width=".8"/>'
            f'<text font-size="6.6" font-weight="700" fill="{yazi}" letter-spacing=".7" '
            f'font-family="Georgia, Times New Roman, serif"><textPath href="#yky{no}" startOffset="50%" '
            f'text-anchor="middle">{metin}</textPath></text>{yildizlar}'
            f'<path d="{LOGO_YOLU}" fill="{yazi}" fill-rule="evenodd" '
            'transform="translate(28 34.5) scale(.147) translate(-10 -50)"/>'
            f'<g clip-path="url(#ykm{no})"><rect class="yk-parilti" x="-30" y="-10" width="16" height="120" '
            f'fill="url(#ykmg{no})" transform="skewX(-18)"/></g></svg>')


def makam(p):
    """Teşkilattan: Müdürlük birimindeki "Müdür" → müdür; müdür yardımcılığı birimindeki → müdür yardımcısı."""
    b = getattr(p, "teskilat_birimi", None)
    if b is None:
        return None
    unvan = str(getattr(p, "gorev_unvani", "") or "").replace("İ", "i").replace("I", "ı").lower().strip()
    # "Müdür", "Yüksekokul Müdürü", "MYO Müdürü (V.)" evet; "Müdürlük Sekreteri", "Müdür Yardımcısı" hayır
    if b.tur == "mudurluk" and re.match(r"^((yüksekokul|myo) )?müdür(ü)?(\s|\(|$)", unvan) and "yard" not in unvan:
        return "mudur"
    if b.tur == "yardimci":
        return "yardimci"
    return None


def gelistirici_nisani(no=0):
    """Geliştirici: turkuaz-mor-pembe geçişli altıgen kalkan, ortada parlayan </>, dönen kesik halka ve iki kıvılcım.
    Hareketler CSS ile (kamyosis.css .gl-*): hareket azaltma tercihinde durur."""
    kod = "M30 31 L21 40 L30 49 M50 31 L59 40 L50 49 M44.5 27 L35.5 53"
    kivilcim = "l1.2 3 3 1.2 -3 1.2 -1.2 3 -1.2 -3 -3 -1.2 3 -1.2z"
    return ('<svg viewBox="0 0 80 80" width="78" height="78" aria-hidden="true">'
            f'<defs><linearGradient id="gl{no}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3ee"/>'
            '<stop offset=".5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#ec4899"/></linearGradient>'
            f'<radialGradient id="gl{no}i" cx="50%" cy="40%" r="65%"><stop offset="0" stop-color="#312e81"/>'
            '<stop offset="1" stop-color="#0b1020"/></radialGradient></defs>'
            f'<polygon points="40,3 72,21.5 72,58.5 40,77 8,58.5 8,21.5" fill="url(#gl{no})"/>'
            f'<polygon points="40,9 66.5,24.5 66.5,55.5 40,71 13.5,55.5 13.5,24.5" fill="url(#gl{no}i)"/>'
            f'<circle class="gl-halka" cx="40" cy="40" r="25" fill="none" stroke="url(#gl{no})" stroke-width="1.6" '
            'stroke-dasharray="3 5"/>'
            f'<path d="{kod}" fill="none" stroke="#22d3ee" stroke-width="8" opacity=".3" stroke-linecap="round" '
            'stroke-linejoin="round"/>'
            f'<path d="{kod}" fill="none" stroke="#fff" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<path class="gl-kivilcim" d="M16 14 {kivilcim}" fill="#fff"/>'
            f'<path class="gl-kivilcim gl-gec" d="M64 62 {kivilcim}" fill="#fff"/></svg>')


def emir_armasi(no=0):
    """Emir astsubayı: kırmızı keçe kalkan üzerinde iki beyaz işlemeli yıldız (kenarı dikişli)."""
    kalkan = "M7 12 Q19 15 31 10 Q43 5 55 4 L55 30 Q55 53 31 64 Q7 53 7 30 Z"
    yildizlar = "".join(
        _yildiz(x, y, 8.2).replace(f'fill="{ALTIN}" stroke="{KOYU}" stroke-width=".6"',
                                   'fill="#fbfbfb" stroke="#d4d4d8" stroke-width=".8"')
        for x, y in ((23, 27), (39, 42)))
    return ('<svg viewBox="0 0 62 68" width="52" height="58" aria-hidden="true">'
            f'<defs><radialGradient id="emr{no}" cx="40%" cy="30%" r="75%">'
            '<stop offset="0" stop-color="#e3263b"/><stop offset="1" stop-color="#a50f22"/></radialGradient></defs>'
            f'<path d="{kalkan}" fill="url(#emr{no})" stroke="#7f0a18" stroke-width="2.2" stroke-linejoin="round"/>'
            f'<path d="{kalkan}" fill="none" stroke="#f05a6b" stroke-width=".9" stroke-dasharray="1.6 1.3" '
            'transform="translate(31 34) scale(.9) translate(-31 -34)"/>'
            f'{yildizlar}</svg>')


def emir_astsubayi_mi(p):
    unvan = str(getattr(p, "gorev_unvani", "") or "").replace("İ", "i").replace("I", "ı").lower()
    return "emir astsubay" in unvan


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
    mk = makam(p)
    if mk:  # makam mühürü idari kadro nişanının yerine geçer
        out.append((muhur(mk, p.pk), "Yüksekokul müdürü" if mk == "mudur" else "Müdür yardımcısı"))
    elif getattr(p, "idari_kadro", False):
        out.append((idari_nisan(p.pk), getattr(p, "gorev_unvani", "") or "İdari kadro"))
    if getattr(p, "gelistirici", False):
        out.append((gelistirici_nisani(p.pk), "Geliştirici"))
    if emir_astsubayi_mi(p):
        out.append((emir_armasi(p.pk), p.gorev_unvani))
    return [(mark_safe(svg), escape(etiket)) for svg, etiket in out]
