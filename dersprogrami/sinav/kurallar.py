"""KAMYOSİS sınav planlama kuralları (program bazlı planlama).

1. Sınavlar ders koduna göre oluşur; aynı kodlu dersler (farklı kısımlar) tek sınavdır.
2. Sınav türü %100 UYG (yalnızca uygulama) olan dersin yazılı sınavı yoktur: plana alınmaz.
3. Zorluk 1–5 (girilmemişse 3): zorluğu yüksek sınav mümkün olduğunca önce yerleşir; eşitse MT içeren türler
   (%100 MT, %40 MT + %60 UYG) önce, ÇS içerenler (%100 ÇS, %40 ÇS + %60 UYG) sona kalır.
4. Adı aynı olan dersler (parantez içi hariç) aynı güne yerleşir.
5. Bir seansta mümkün olduğunca tek sınıf düzeyi (ders kodunun ilk rakamı: 1xx = 1. sınıf, 2xx = 2. sınıf) olur.

Kurallar çözücüye PExam alanlarıyla geçer (bkz. solver.py: difficulty, family, year, base_name).
"""

import re

VARSAYILAN_ZORLUK = 3
ZORLUKLAR = [1, 2, 3, 4, 5]
SIK_TURLER = ["%100 MT", "%40 MT + %60 UYG", "%100 ÇS", "%40 ÇS + %60 UYG", "%100 UYG"]

MT, CS, DIGER, UYG = "MT", "ÇS", "", "UYG"  # eşit zorlukta sıra: MT > diğer > ÇS (solver.TYPE_RANK)

_PARCA = re.compile(r"%?\s*(\d{1,3})\s*%?\s*([A-Za-zÇĞİÖŞÜçğıöşü]+)")
_PARANTEZ = re.compile(r"\([^)]*\)")
_YIL = re.compile(r"(\d)\d\d")  # 3 haneli ders numarasının ilk rakamı


def _kisaltma(metin):
    k = metin.upper().replace("İ", "I")
    return "ÇS" if k in ("ÇS", "CS") else k


def tur_parcalari(metin):
    """"%40 MT + %60 UYG" → [(40, "MT"), (60, "UYG")]."""
    return [(int(oran), _kisaltma(kod)) for oran, kod in _PARCA.findall(metin or "")]


def tur_normalize(metin):
    """Excel ve elle girişteki yazım farklarını tek biçime getirir: "40% mt+60%uyg" → "%40 MT + %60 UYG"."""
    parcalar = tur_parcalari(metin)
    if not parcalar:
        return (metin or "").strip()
    return " + ".join(f"%{oran} {kod}" for oran, kod in parcalar)


def tur_ailesi(metin):
    """UYG: yalnızca uygulama (plana alınmaz), MT, ÇS ya da "" (bilinmiyor / diğer)."""
    kodlar = {kod for _, kod in tur_parcalari(metin)}
    if not kodlar:
        return DIGER
    if kodlar == {UYG}:
        return UYG
    if MT in kodlar:
        return MT
    if CS in kodlar:
        return CS
    return DIGER


def plana_alinmaz(metin):
    return tur_ailesi(metin) == UYG


def zorluk(deger):
    try:
        z = int(deger)
    except (TypeError, ValueError):
        return VARSAYILAN_ZORLUK
    return z if z in ZORLUKLAR else VARSAYILAN_ZORLUK


def ders_kodu(subject):
    """Ders adının kodu: kısa adı (aSc'de ders kodu, ör. BİL103), yoksa adı."""
    return (subject.short or subject.name or "").strip()


def temel_ad(ad):
    """Parantez içi hariç karşılaştırma adı: "Askerî Harekâtın Yönetimi 1 (SVN)" → "askerî harekâtın yönetimi 1"."""
    return " ".join(_PARANTEZ.sub(" ", ad or "").casefold().split())


def sinif_yili(kod):
    """Ders numarasının (3 hane) ilk rakamı sınıf düzeyidir: BİL103 → 1, ASK201 → 2; T3 gibi kodlarda None."""
    m = _YIL.search(kod or "")
    return int(m.group(1)) if m else None


_KISIM = re.compile(r"^\s*(\d+)\s*([^\d\s].*?)\s*$")
# Kısım numarası → sınıf düzeyi (KAMYOSİS kısım numaralandırması)
KISIM_ARALIKLARI = ((1, 36, 2), (50, 86, 1))


def kisim_bilgisi(kisa_ad):
    """Kısım kısa adından (program, sınıf düzeyi): "10MKT" → ("MKT", 2), "56SVN" → ("SVN", 1).
    Program sayıdan sonraki kısımdır; sınıf düzeyi numaradan (1–36 → 2. sınıf, 50–86 → 1. sınıf; aralık dışı None).
    Biçime uymayan ad ("Hazırlık 1") → ("", None)."""
    m = _KISIM.match(kisa_ad or "")
    if not m:
        return "", None
    no = int(m.group(1))
    return buyuk(m.group(2)), next((s for bas, son, s in KISIM_ARALIKLARI if bas <= no <= son), None)


def buyuk(metin):
    """Türkçe büyük harf: "inş" → "İNŞ"."""
    return (metin or "").replace("i", "İ").replace("ı", "I").upper()


def kontenjan_dagit(toplam, siniflar):
    """Programın kontenjanını kısımlara eşit böler (artan ilk kısımlara): {sınıf kimliği: öğrenci}."""
    if not siniflar:
        return {}
    pay, artan = divmod(max(0, toplam), len(siniflar))
    return {c.pk: pay + (1 if i < artan else 0) for i, c in enumerate(siniflar)}


def bilgiler(institution_id):
    """{ders kodu: ExamCourse} — kurumun ders sınav bilgileri."""
    from .models import ExamCourse

    return {c.code: c for c in ExamCourse.objects.filter(institution_id=institution_id)}
