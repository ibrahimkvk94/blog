"""T.C. kimlik kartı (2017 sonrası çipli kart) okuma kuralları.

Bu dosya Django'ya ve yazı okuma (OCR) motoruna bağlı DEĞİLDİR: girdi, motorun bulduğu metin parçalarıdır
(konumlarıyla), çıktı kimlik bilgileridir. İleride internetsiz mobil uygulamaya aynı kurallarla aktarılmak üzere
ayrı tutuldu; yalnız Python standart kitaplığını kullanır.

Kartın iki yüzü birbirine karşı denetlenir:
- Arka yüzdeki 3 satırlık makine okunur bölge (MRZ, ICAO 9303 TD1) belge no, doğum tarihi, cinsiyet, son
  geçerlilik ve T.C. no'yu kontrol haneleriyle verir; yanlış okunan rakam yakalanır.
- MRZ'de Türkçe harf yoktur ("ŞÜKRÜ" → "SUKRU"); ad ve soyad ön yüzden okunur, MRZ ile karşılaştırılır.
- Anne adı, baba adı, veren makam arka yüzün etiketli alanlarından okunur.

Kullanım:
    sonuc = birlestir(on_parcalari, arka_parcalari, mrz_metinleri)
    sonuc.bilgiler   # {"tc": "...", "soyad": "...", ...}
    sonuc.uyarilar   # ["Ön yüzdeki ad ile kod satırı farklı ...", ...]
    sonuc.supheli    # {"ad", ...} — önizlemede işaretlenecek alanlar
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from dataclasses import dataclass, field
from itertools import cycle

ALANLAR = [
    ("tc", "T.C. Kimlik No"),
    ("soyad", "Soyadı"),
    ("ad", "Adı"),
    ("dogum_tarihi", "Doğum Tarihi"),
    ("cinsiyet", "Cinsiyeti"),
    ("seri_no", "Seri No"),
    ("uyruk", "Uyruğu"),
    ("son_gecerlilik", "Son Geçerlilik"),
    ("anne_adi", "Anne Adı"),
    ("baba_adi", "Baba Adı"),
    ("veren_makam", "Veren Makam"),
]
ALAN_ADLARI = dict(ALANLAR)
CINSIYET = {"E": "Erkek", "K": "Kadın"}


@dataclass
class Parca:
    """Motorun bulduğu bir metin satırı ve kutusu (piksel)."""

    metin: str
    sol: int = 0
    ust: int = 0
    sag: int = 0
    alt: int = 0

    @property
    def yukseklik(self):
        return max(self.alt - self.ust, 1)


@dataclass
class Sonuc:
    bilgiler: dict = field(default_factory=dict)
    uyarilar: list = field(default_factory=list)
    supheli: set = field(default_factory=set)

    def uyar(self, metin, *alanlar):
        if metin not in self.uyarilar:
            self.uyarilar.append(metin)
        self.supheli.update(alanlar)


# ----------------------------------------------------------------------------------------------- yardımcılar

_ASCII = str.maketrans("ÇĞİÖŞÜçğıöşüÂÎÛâîû", "CGIOSUcgiosuAIUaiu")


def ascii_buyuk(metin):
    """Türkçe harfleri sadeleştirip büyütür: "Şükrü Çağlar" → "SUKRU CAGLAR" (MRZ ile karşılaştırma)."""
    return " ".join((metin or "").translate(_ASCII).upper().split())


def tr_buyuk(metin):
    return (metin or "").replace("i", "İ").replace("ı", "I").upper()


def tr_kucuk(metin):
    return (metin or "").replace("İ", "i").replace("I", "ı").lower()


def tr_baslik(metin):
    """"ALİ IŞIK" → "Ali Işık"."""
    return " ".join(tr_buyuk(k[:1]) + tr_kucuk(k[1:]) for k in (metin or "").split())


def sade(metin):
    """Etiket eşleştirme için: küçük, Türkçe harfsiz, aksansız."""
    s = tr_kucuk(metin).translate(_ASCII)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def tc_gecerli(tc):
    """T.C. kimlik no algoritması: 11 hane, ilk hane 0 değil, 10. ve 11. haneler kontrol hanesi."""
    if not re.fullmatch(r"[1-9]\d{10}", tc or ""):
        return False
    d = [int(c) for c in tc]
    if (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def kontrol_hanesi(metin):
    """ICAO 9303 kontrol hanesi (ağırlıklar 7-3-1; harf = 10..35, '<' = 0)."""
    toplam = 0
    for c, a in zip(metin, cycle((7, 3, 1))):
        if c.isdigit():
            d = int(c)
        elif "A" <= c <= "Z":
            d = ord(c) - 55
        else:
            d = 0
        toplam += d * a
    return str(toplam % 10)


# OCR'ın sık karıştırdığı harf / rakamlar
_RAKAMA = str.maketrans("OQDUILZSGB", "0000112568")
_HARFE = str.maketrans("0125683", "OIZSGBE")


def rakamlastir(metin):
    return (metin or "").translate(_RAKAMA)


def harflestir(metin):
    return (metin or "").translate(_HARFE)


def _seri_duzelt(metin):
    """T.C. kimlik kartı seri no biçimi: harf, 2 rakam, harf, 5 rakam (ör. A12B34567)."""
    m = (metin or "").upper()
    if len(m) != 9:
        return m
    return harflestir(m[0]) + rakamlastir(m[1:3]) + harflestir(m[3]) + rakamlastir(m[4:])


def _tarih(gun, ay, yil):
    try:
        return datetime.date(int(yil), int(ay), int(gun))
    except ValueError:
        return None


# ----------------------------------------------------------------------------------------------- MRZ (arka yüz)

@dataclass
class Mrz:
    satirlar: list
    belge_no: str = ""
    belge_dogru: bool = False
    tc: str = ""
    dogum_tarihi: datetime.date | None = None
    dogum_dogru: bool = False
    cinsiyet: str = ""
    son_gecerlilik: datetime.date | None = None
    son_dogru: bool = False
    uyruk: str = ""
    soyad: str = ""
    ad: str = ""
    bilesik_dogru: bool = False


def _mrz_sade(metin):
    m = (metin or "").upper().replace("«", "<").replace("‹", "<")
    return re.sub(r"[^A-Z0-9<]", "", m)


_SATIR2 = re.compile(r"[0-9]{7}[MF<][0-9]{7}[A-Z<]{3}")


def _satir2_mi(s):
    if len(s) < 19:
        return False
    aday = rakamlastir(s[0:7]) + s[7] + rakamlastir(s[8:15]) + harflestir(s[15:18])
    return bool(_SATIR2.fullmatch(aday))


def _doldur(s, bas):
    """OCR dolgu '<' sayısını yanlış okuyabilir: sabit uzunluktaki baş kısmı koruyup satırı 30 karaktere getirir.
    bas: verinin bittiği yer; sonrası '<' dolgu (+ satır 2'de son hane genel kontrol hanesi)."""
    if len(s) == 30:
        return s
    if bas == 18 and re.fullmatch(r"<*[0-9OQDILSB]", s[18:]):  # satır 2: dolgu + genel kontrol hanesi
        return s[:18] + "<" * 11 + s[-1]
    if re.fullmatch(r"<*", s[bas:]):
        return (s[:bas] + "<" * 30)[:30]
    return (s + "<" * 30)[:30]


def mrz_puani(m):
    return (m.belge_dogru + m.dogum_dogru + m.son_dogru + 2 * m.bilesik_dogru + tc_gecerli(m.tc)
            + m.satirlar[2].count("<") / 100)  # ad satırında '<' → 'K' okunması daha az dolgu bırakır


def mrz_bul(metinler):
    """OCR satırları (bir ya da birkaç okumanın satırları birlikte) içinden TD1 MRZ'nin 3 satırını bulur.
    Her satır türü için adaylar toplanır, kontrol hanelerinin en çok tuttuğu birleşim seçilir; yoksa None."""
    adaylar = [a for a in (_mrz_sade(m) for m in metinler) if len(a) >= 20 and "<" in a]
    s1ler, s2ler, s3ler = [], [], []
    for a in adaylar:
        if _satir2_mi(a):
            s2ler.append(_doldur(a, 18))
        elif re.match(r"[I1][<A-Z0-9]?TUR", a) or (a[:1] in "I1" and len(a) >= 25 and a[1:2] in "<D"):
            s1ler.append(_doldur(a, 26))
        elif "<<" in a and sum(c.isalpha() for c in a) >= 4 and not any(c.isdigit() for c in a):
            s3ler.append(_doldur(a, len(a.rstrip("<"))))
    if not (s1ler and s2ler and s3ler):
        return None
    tekil = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    en_iyi = max(((a, b, c) for a in tekil(s1ler) for b in tekil(s2ler) for c in tekil(s3ler)),
                 key=lambda u: mrz_puani(mrz_coz(u)))
    return list(en_iyi)


def mrz_coz(satirlar):
    """3 satırlık TD1 MRZ'yi çözer. Rakam olması gereken yerlerde O/0, I/1, S/5, B/8 karışıklıklarını düzeltir."""
    s1, s2, s3 = [(x + "<" * 30)[:30] for x in satirlar]
    m = Mrz(satirlar=[s1, s2, s3])

    belge = s1[5:14]
    kh = rakamlastir(s1[14])
    duz = _seri_duzelt(belge)
    secilen = duz
    for aday in (belge, duz):
        if kontrol_hanesi(aday) == kh:
            secilen, m.belge_dogru = aday, True
            break
    m.belge_no = secilen.replace("<", "")

    tc = rakamlastir(s1[15:26])
    m.tc = tc if re.fullmatch(r"\d{11}", tc) else ""

    dogum, dkh = rakamlastir(s2[0:6]), rakamlastir(s2[6])
    son, skh = rakamlastir(s2[8:14]), rakamlastir(s2[14])
    bugun = datetime.date.today()
    if re.fullmatch(r"\d{6}", dogum):
        yy = int(dogum[:2])
        yil = 2000 + yy if 2000 + yy <= bugun.year else 1900 + yy
        m.dogum_tarihi = _tarih(dogum[4:6], dogum[2:4], yil)
        m.dogum_dogru = m.dogum_tarihi is not None and kontrol_hanesi(dogum) == dkh
    if re.fullmatch(r"\d{6}", son):
        m.son_gecerlilik = _tarih(son[4:6], son[2:4], 2000 + int(son[:2]))
        m.son_dogru = m.son_gecerlilik is not None and kontrol_hanesi(son) == skh
    m.cinsiyet = {"M": "E", "F": "K"}.get(s2[7], "")
    m.uyruk = harflestir(s2[15:18]).replace("<", "")

    bilesik = secilen + kh + rakamlastir(s1[15:30]) + dogum + dkh + son + skh + s2[18:29]
    m.bilesik_dogru = kontrol_hanesi(bilesik) == rakamlastir(s2[29])

    isim = harflestir(s3).strip("<")
    soyad, _, ad = isim.partition("<<")
    m.soyad = " ".join(soyad.replace("<", " ").split())
    m.ad = " ".join(ad.replace("<", " ").split())
    return m


# ----------------------------------------------------------------------------------------------- etiketli alanlar

_ETIKETLER = {
    "soyad": lambda s: "soyad" in s or "surname" in s,
    "ad": lambda s: ("given" in s or re.match(r"^\W*adi\b", s) is not None) and "soyad" not in s,
    "anne_adi": lambda s: "anne" in s or "mother" in s,
    "baba_adi": lambda s: "baba" in s or "father" in s,
    "veren_makam": lambda s: "veren" in s or "issued" in s,
}
_HER_ETIKET = ("kimlik", "identity", "dogum", "birth", "cinsiyet", "gender", "seri no", "document", "uyrug",
               "nationality", "gecerlilik", "valid", "imza", "signature", "republic", "turkiye", "turkey",
               "cumhuriyeti")
_AD_DESENI = re.compile(r"[A-ZÇĞİÖŞÜÂÎÛ][A-ZÇĞİÖŞÜÂÎÛ '\-.]*")


def _etiket_mi(parca):
    s = sade(parca.metin)
    return any(f(s) for f in _ETIKETLER.values()) or any(e in s for e in _HER_ETIKET) or "/" in parca.metin


def _deger_temizle(metin, ad_mi=True):
    m = " ".join((metin or "").split())
    if ad_mi:
        m = tr_buyuk(m)
        m = re.sub(r"[^A-ZÇĞİÖŞÜÂÎÛ '\-]", "", m)
    return " ".join(m.split())


def deger_sec(alan, metin):
    """Ham metni alanın değeri olarak temizler; uygun değilse ""."""
    if alan == "veren_makam":
        deger = tr_buyuk(" ".join((metin or "").split()))
        deger = re.sub(r"^[^A-ZÇĞİÖŞÜ0-9]+|[^A-ZÇĞİÖŞÜ0-9.]+$", "", deger)
        return deger if len(deger.replace(" ", "")) >= 3 else ""
    deger = _deger_temizle(metin)
    return deger if len(deger.replace(" ", "")) >= 2 and _AD_DESENI.fullmatch(deger) else ""


def etiket_bul(parcalar, alan):
    kosul = _ETIKETLER[alan]
    return next((p for p in parcalar if kosul(sade(p.metin))), None)


def deger_kutusu(et, parcalar):
    """Etiketin altındaki değer bölgesi (sol, üst, sağ, alt): bir sonraki etikete kadar, en çok 3,5 etiket boyu."""
    h = et.yukseklik
    alt = et.alt + h * 2.6
    for p in parcalar:  # aynı sütunda alttaki ilk etiket bölgeyi keser
        if p is not et and _etiket_mi(p) and p.ust > et.ust + h * 0.5 and abs(p.sol - et.sol) < h * 4:
            alt = min(alt, p.ust)
    sag = et.sol + h * 18
    for p in parcalar:  # sağdaki sütunun etiketi / değeri bölgeye girmesin
        if p is not et and p.sol > et.sag + h and p.alt > et.ust and p.ust < alt:
            sag = min(sag, p.sol - h * 0.3)
    return (max(et.sol - h, 0), et.alt, max(sag, et.sag), alt)


def etiketli_alanlar(parcalar, alanlar):
    """Etiketin hemen altındaki (sola hizalı) satırı değer olarak alır: {"soyad": "KAYA", ...}.
    Değer, alttaki bir sonraki etiketi geçmez (anne adı yerine baba adı alınmaz)."""
    sonuc = {}
    for alan in alanlar:
        et = etiket_bul(parcalar, alan)
        if et is None:
            continue
        h = et.yukseklik
        _, _, _, sinir = deger_kutusu(et, parcalar)
        adaylar = sorted((p for p in parcalar if p is not et and p.ust > et.ust + h * 0.5 and p.ust < sinir
                          and abs(p.sol - et.sol) < h * 4 and not _etiket_mi(p)),
                         key=lambda p: (p.ust, abs(p.sol - et.sol)))
        for p in adaylar:
            deger = deger_sec(alan, p.metin)
            if deger:
                sonuc[alan] = deger
                break
    return sonuc


# ----------------------------------------------------------------------------------------------- ön yüz

_TARIH_DESENI = re.compile(r"(?<!\d)(\d{2})\s*[./,\-]\s*(\d{2})\s*[./,\-]\s*(\d{4})(?!\d)")


def on_yuz(parcalar):
    """Ön yüzden: T.C. no, ad, soyad, doğum tarihi, cinsiyet, seri no, uyruk, son geçerlilik."""
    b = {}
    metinler = [p.metin for p in parcalar]
    tum = " ".join(metinler)

    tcler = []
    for m in metinler + [tum]:
        tcler += [t for t in re.findall(r"(?<!\d)\d{11}(?!\d)", m) if t not in tcler]
    for m in metinler + [tum]:
        for aday in re.findall(r"(?<![0-9A-Z])[0-9OQDILSB ]{11,15}(?![0-9A-Z])", m.upper()):
            aday = rakamlastir(aday.replace(" ", ""))
            if len(aday) == 11 and aday not in tcler:
                tcler.append(aday)
    gecerli = [t for t in tcler if tc_gecerli(t)]
    if gecerli:
        b["tc"] = gecerli[0]
    elif tcler:
        b["tc_ham"] = tcler[0]

    tarihler = sorted({t for t in (_tarih(*g) for g in _TARIH_DESENI.findall(tum)) if t})
    if len(tarihler) >= 2:
        b["dogum_tarihi"], b["son_gecerlilik"] = tarihler[0], tarihler[-1]
    elif len(tarihler) == 1:
        anahtar = "son_gecerlilik" if tarihler[0] > datetime.date.today() else "dogum_tarihi"
        b[anahtar] = tarihler[0]

    m = re.search(r"(?<![A-ZÇĞİÖŞÜ])([EK])\s*/\s*([MF])(?![A-Z])", tr_buyuk(tum))
    if m:
        b["cinsiyet"] = m.group(1)

    for kelime in re.findall(r"\b[A-Z0-9]{9}\b", re.sub(r"[^A-Z0-9 ]", " ", tum.upper())):
        aday = _seri_duzelt(kelime)
        if re.fullmatch(r"[A-Z]\d{2}[A-Z]\d{5}", aday) and not re.fullmatch(r"\d{9}", kelime):
            b["seri_no"] = aday
            break

    if re.search(r"T\.?\s?C\.?\s*/\s*TUR|\bTUR\b", tum.upper()):
        b["uyruk"] = "T.C."

    b.update(etiketli_alanlar(parcalar, ["soyad", "ad"]))
    return b


def arka_yuz(parcalar):
    return etiketli_alanlar(parcalar, ["anne_adi", "baba_adi", "veren_makam"])


# ----------------------------------------------------------------------------------------------- birleştirme

def _ayni_ad(on, mrz_degeri):
    return bool(on) and ascii_buyuk(on).replace(" ", "") == (mrz_degeri or "").replace(" ", "")


def _ad_karsilastir(sonuc, alan, on, mrz_degeri):
    """Ön yüzdeki ad/soyad Türkçe harfli doğru biçimdir; MRZ ile ASCII olarak karşılaştırılır."""
    ad = ALAN_ADLARI[alan].lower()
    if on and mrz_degeri:
        if ascii_buyuk(on).replace(" ", "") != mrz_degeri.replace(" ", ""):
            sonuc.uyar(f"{ALAN_ADLARI[alan]}: ön yüzde “{on}”, kod satırında “{mrz_degeri}” okundu; "
                       f"lütfen karttan kontrol edin.", alan)
        return on
    if on:
        return on
    if mrz_degeri:
        sonuc.uyar(f"{ALAN_ADLARI[alan]} ön yüzden okunamadı, kod satırından alındı (“{mrz_degeri}”). Kod satırında "
                   f"Türkçe harf yoktur: Ç, Ğ, İ, Ö, Ş, Ü harflerini düzeltin.", alan)
        return mrz_degeri
    sonuc.uyar(f"{ALAN_ADLARI[alan]} okunamadı.", alan)
    return ""


def birlestir(on_parcalari=(), arka_parcalari=(), mrz_metinleri=(), bolgeler=None):
    """İki yüzün okumasını birleştirir ve denetler. Parçalar `Parca` listesi, mrz_metinleri düz satırlardır.
    bolgeler: {alan: metin} — motorun etiketin altındaki bölgeyi ayrıca tek satır olarak okuduğu değerler; geçerliyse
    genel okumadan önce gelir."""
    sonuc = Sonuc()
    on = on_yuz(list(on_parcalari)) if on_parcalari else {}
    arka = arka_yuz(list(arka_parcalari)) if arka_parcalari else {}
    satirlar = mrz_bul(list(mrz_metinleri) + [p.metin for p in arka_parcalari])
    mrz = mrz_coz(satirlar) if satirlar else None
    for alan, metin in (bolgeler or {}).items():
        deger = deger_sec(alan, metin)
        if not deger:
            continue
        hedef = on if alan in ("soyad", "ad") else arka
        mrz_degeri = getattr(mrz, alan, "") if mrz is not None and alan in ("soyad", "ad") else ""
        if mrz_degeri:  # iki okumadan kod satırıyla tutan seçilir
            if _ayni_ad(hedef.get(alan), mrz_degeri) or not (_ayni_ad(deger, mrz_degeri) or not hedef.get(alan)):
                continue
        hedef[alan] = deger
    if not on_parcalari:
        sonuc.uyar("Ön yüz fotoğrafı yok: ad ve soyad kod satırından (Türkçe harfsiz) alınır.")
    if arka_parcalari and mrz is None:
        sonuc.uyar("Arka yüzdeki kod satırları (MRZ) okunamadı; fotoğrafı daha yakından ve parlamasız çekin.")
    if mrz is not None and not mrz.bilesik_dogru:
        sonuc.uyar("Kod satırlarının genel kontrol hanesi tutmadı; okunan değerleri kontrol edin.")
    b = sonuc.bilgiler

    # T.C. kimlik no
    adaylar = []
    if on.get("tc"):
        adaylar.append(("ön yüz", on["tc"]))
    if mrz is not None and tc_gecerli(mrz.tc):
        adaylar.append(("kod satırı", mrz.tc))
    if adaylar:
        b["tc"] = adaylar[0][1]
        if len({t for _, t in adaylar}) > 1:
            sonuc.uyar(f"T.C. kimlik no ön yüzde {on['tc']}, kod satırında {mrz.tc} okundu.", "tc")
    else:
        b["tc"] = on.get("tc_ham") or (mrz.tc if mrz else "")
        sonuc.uyar("T.C. kimlik no okunamadı ya da kontrol hanesi tutmuyor.", "tc")

    # MRZ'de kontrol hanesi olan alanlar önce MRZ'den
    def kontrollu(alan, mrz_degeri, dogru, on_degeri):
        if mrz_degeri and dogru:
            if on_degeri and on_degeri != mrz_degeri:
                sonuc.uyar(f"{ALAN_ADLARI[alan]}: ön yüz ile kod satırı farklı; kod satırındaki (kontrol hanesi "
                           f"tutan) değer alındı.", alan)
            return mrz_degeri
        if on_degeri:
            if mrz is not None:
                sonuc.supheli.add(alan)
            return on_degeri
        if mrz_degeri:
            sonuc.uyar(f"{ALAN_ADLARI[alan]} kod satırından okundu ama kontrol hanesi tutmadı.", alan)
            return mrz_degeri
        sonuc.uyar(f"{ALAN_ADLARI[alan]} okunamadı.", alan)
        return None

    b["seri_no"] = kontrollu("seri_no", mrz.belge_no if mrz else "", mrz.belge_dogru if mrz else False,
                             on.get("seri_no", "")) or ""
    b["dogum_tarihi"] = kontrollu("dogum_tarihi", mrz.dogum_tarihi if mrz else None,
                                  mrz.dogum_dogru if mrz else False, on.get("dogum_tarihi"))
    b["son_gecerlilik"] = kontrollu("son_gecerlilik", mrz.son_gecerlilik if mrz else None,
                                    mrz.son_dogru if mrz else False, on.get("son_gecerlilik"))
    b["cinsiyet"] = (mrz.cinsiyet if mrz and mrz.cinsiyet else "") or on.get("cinsiyet", "")
    if mrz and mrz.cinsiyet and on.get("cinsiyet") and on["cinsiyet"] != mrz.cinsiyet:
        sonuc.uyar("Cinsiyet ön yüz ile kod satırında farklı okundu.", "cinsiyet")
    if not b["cinsiyet"]:
        sonuc.uyar("Cinsiyet okunamadı.", "cinsiyet")
    uyruk = on.get("uyruk") or ("T.C." if mrz and mrz.uyruk == "TUR" else (mrz.uyruk if mrz else ""))
    b["uyruk"] = uyruk

    b["soyad"] = _ad_karsilastir(sonuc, "soyad", on.get("soyad", ""), mrz.soyad if mrz else "")
    b["ad"] = _ad_karsilastir(sonuc, "ad", on.get("ad", ""), mrz.ad if mrz else "")

    for alan in ("anne_adi", "baba_adi", "veren_makam"):
        b[alan] = arka.get(alan, "")
        if arka_parcalari and not b[alan]:
            sonuc.uyar(f"{ALAN_ADLARI[alan]} okunamadı.", alan)

    if b.get("son_gecerlilik") and b["son_gecerlilik"] < datetime.date.today():
        sonuc.uyar("Kimlik kartının geçerlilik süresi dolmuş.", "son_gecerlilik")
    return sonuc
