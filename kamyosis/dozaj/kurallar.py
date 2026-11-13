"""Dozajmatik varsayılanları: branş listesi, ders kodundan branş, personelin bölümünden branş önerisi, kadro sınıfı.

Bunlar yalnız başlangıç önerisidir; kullanıcı ekrandan değiştirir (KodBransi, KisiAyari)."""

import re

# (grup, branş, sıra, hesapta) — Plan Program Kısmı'nın 2026-2027 tablosundaki sırayla
BRANSLAR = [
    ("BEŞERİ VE SOSYAL BİLİMLER", "TARİH"), ("BEŞERİ VE SOSYAL BİLİMLER", "HUKUK"),
    ("BEŞERİ VE SOSYAL BİLİMLER", "TÜRK DİLİ"),
    ("TEMEL BİLİMLER", "MATEMATİK"), ("TEMEL BİLİMLER", "FİZİK"),
    ("İŞLETME YÖNETİMİ", "İSTATİSTİK"), ("İŞLETME YÖNETİMİ", "İŞLETME"), ("İŞLETME YÖNETİMİ", "İKTİSAT"),
    ("YABANCI", "YABANCI"), ("ELEKTRİK", "ELEKTRİK"), ("ELEKTRONİK", "ELEKTRONİK"), ("BİLGİSAYAR", "BİLGİSAYAR"),
    ("OTOMOTİV", "OTOMOTİV"), ("MEKATRONİK", "MEKATRONİK"), ("UÇAK", "UÇAK"), ("YAPI TESİSAT", "YAPI TESİSAT"),
    ("İNŞAAT", "İNŞAAT"), ("ASKERİ", "ASKERİ"),
    ("SAVUNMA HİZMETLERİ", "SAVUNMA"), ("SAVUNMA HİZMETLERİ", "İSTATİSTİK SVN"), ("SAVUNMA HİZMETLERİ", "SAĞLIK"),
    ("SAVUNMA HİZMETLERİ", "ULUSLARASI"),
]
HESAP_DISI = [("DİĞER", "AFET")]  # Afet farkındalık: tabloya girmez, ayrıca gösterilir

# Ders kodunun ilk üç harfi → branş
ONEK = {
    "YDL": "YABANCI", "ASK": "ASKERİ", "ELK": "ELEKTRİK", "ELN": "ELEKTRONİK", "BİL": "BİLGİSAYAR",
    "OTT": "OTOMOTİV", "MKT": "MEKATRONİK", "UÇT": "UÇAK", "YTT": "YAPI TESİSAT", "İNŞ": "İNŞAAT",
    "SVN": "SAVUNMA", "İŞL": "İŞLETME", "UZE": "AFET",
}
# Önekten farklı olanlar (2026-2027 tablosundaki saatlerle karşılaştırılarak seçildi)
OZEL = {
    "TEM100": "FİZİK", "TEM103": "FİZİK", "TEM101": "MATEMATİK", "TEM102": "MATEMATİK",
    "BSB101": "TÜRK DİLİ", "BSB102": "TÜRK DİLİ",
    "BSB103": "TARİH", "BSB104": "TARİH", "BSB220": "TARİH", "BSB203": "TARİH", "BSB210": "TARİH",
    "BSB110": "HUKUK", "BSB114": "HUKUK", "BSB204": "HUKUK",
    "İŞL201": "İSTATİSTİK", "İŞL214": "İSTATİSTİK", "İŞL213": "İSTATİSTİK SVN", "İŞL218": "İSTATİSTİK SVN",
    "İŞL103": "İKTİSAT", "İŞL104": "İKTİSAT", "İŞL203": "İKTİSAT", "İŞL116": "İKTİSAT",
    "İŞL118": "BİLGİSAYAR", "İŞL112": "SAVUNMA",
    "MKT213": "ELEKTRİK", "MKT106": "ELEKTRİK",
    "SVN102": "ULUSLARASI", "SVN203": "ULUSLARASI", "SVN205": "SAĞLIK", "SVN108": "SAĞLIK",
}

# Personelin bölümü (personel.Bolum.kod) → önerilen branş. Temel Bilimler ve Beşeri Bilimler birden çok branş
# içerdiği için öneri yok; kartındaki "Branş" yazısı tutarsa o kullanılır.
BOLUM_BRANSI = {
    "BİL": "BİLGİSAYAR", "ELK": "ELEKTRİK", "ELN": "ELEKTRONİK", "İNŞ": "İNŞAAT", "İŞL": "İŞLETME",
    "MKT": "MEKATRONİK", "OTT": "OTOMOTİV", "SVN": "SAVUNMA", "UÇT": "UÇAK", "YTT": "YAPI TESİSAT",
    "ASK": "ASKERİ", "YDL": "YABANCI",
}
# Kart "Branş" yazısı → branş
BRANS_ESLERI = {"EDEBİYAT": "TÜRK DİLİ", "TÜRK DİLİ VE EDEBİYATI": "TÜRK DİLİ", "ULUSLARARASI İLİŞKİLER": "ULUSLARASI",
                "İNGİLİZCE": "YABANCI", "YABANCI DİL": "YABANCI", "ASKERÎ": "ASKERİ"}


def buyuk(metin):
    """Türkçe büyük harf (i → İ, ı → I)."""
    return (metin or "").replace("i", "İ").replace("ı", "I").upper().strip()


def kod_bransi(kod):
    """Ders kodundan varsayılan branş adı ya da None."""
    kod = buyuk(kod).replace(" ", "")
    return OZEL.get(kod) or ONEK.get(kod[:3])


def brans_oneri_adi(personel):
    """Kartından önerilen branş adı (yalnız derse girebilenler) ya da None."""
    if not personel.derse_girebilir:
        return None
    yazi = buyuk(personel.brans)
    if yazi:
        yazi = BRANS_ESLERI.get(yazi, yazi)
        if yazi in {b for _, b in BRANSLAR}:
            return yazi
    kod = buyuk(getattr(personel.bolum, "kod", "") or "")
    return BOLUM_BRANSI.get(kod)


def otomatik_kadro(personel, baskanlar):
    """Kart bilgisinden kadro sınıfı: bölüm başkanı, astsubay ("Asb." ile başlayan rütbe), yedek subay (Atğm.),
    subay (başka rütbe), sivil (rütbesiz)."""
    from .models import KisiAyari as K

    if personel.pk in baskanlar:
        return K.BB
    rutbe = str(personel.rutbe or "").strip()
    if not rutbe:
        return K.SIVIL
    if rutbe.startswith("Asb"):
        return K.ASB
    if re.search(r"(^|[\s.])Atğm", rutbe):
        return K.YEDEK
    return K.SB
