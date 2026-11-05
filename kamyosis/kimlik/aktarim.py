"""Okunan kimlik satırlarının personel kartlarına ya da öğrenci kaydına aktarılması.

Kurallar:
- Yalnız türü seçilmiş, T.C. no'su geçerli, adı ve soyadı dolu satırlar aktarılır; aynı satır ikinci kez aktarılmaz.
- Personel: T.C. no ile eşleşir. Bulunamazsa T.C. no'su boş tek personelle ad soyad (Türkçe harf duyarsız) ile eşleşir
  ve T.C. no karta yazılır; aynı adda birden fazla personel varsa atlanır; hiç yoksa yeni personel kartı açılır.
  Kimlik bilgileri kartın "Kimlik" başlığındaki alanlara yazılır. Var olan personelin ad soyadı değiştirilmez.
- Öğrenci: T.C. no ile eşleşir, bulunamazsa yeni öğrenci kaydı açılır; kimlik bilgileri kayda yazılır.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from personel.models import KartAlani, KartDegeri, Personel
from ogrenci.models import Ogrenci
from program.asc import ad_anahtari

from .models import KimlikKaydi
from .okuma import CINSIYET, tc_gecerli

# Personel kartında kimlik bilgilerinin yazıldığı ek alanlar: (alan adı, tür, seçenekler, sıra, kayıttaki alan)
KART_ALANLARI = [
    ("Doğum tarihi", KartAlani.TARIH, "", 10, "dogum_tarihi"),
    ("Cinsiyet", KartAlani.SECIM, "Erkek, Kadın", 12, "cinsiyet"),
    ("Uyruğu", KartAlani.METIN, "", 14, "uyruk"),
    ("Anne adı", KartAlani.METIN, "", 40, "anne_adi"),
    ("Baba adı", KartAlani.METIN, "", 42, "baba_adi"),
    ("Kimlik seri no", KartAlani.METIN, "", 50, "seri_no"),
    ("Kimlik son geçerlilik", KartAlani.TARIH, "", 52, "son_gecerlilik"),
    ("Kimliği veren makam", KartAlani.METIN, "", 54, "veren_makam"),
]
OGRENCI_ALANLARI = ["tc", "soyad", "ad", "dogum_tarihi", "cinsiyet", "seri_no", "uyruk", "son_gecerlilik",
                    "anne_adi", "baba_adi", "veren_makam"]

GUNCELLE, YENI, ATLA = "guncelle", "yeni", "atla"


@dataclass
class Plan:
    kayit: KimlikKaydi
    islem: str = ATLA
    hedef: object = None
    notlar: list = field(default_factory=list)

    @property
    def aktarilir(self):
        return self.islem != ATLA


def _kart_degeri(k, alan):
    deger = getattr(k, alan)
    if not deger:
        return ""
    if alan == "cinsiyet":
        return CINSIYET.get(deger, "")
    if hasattr(deger, "isoformat"):
        return deger.isoformat()
    return str(deger)


def _ad_esler(qs, k):
    anahtar = ad_anahtari(k.ad_soyad)
    return [x for x in qs if ad_anahtari(x.ad_soyad) == anahtar]


def planla(kayitlar, personel_yetkisi=False, ogrenci_yetkisi=False):
    """Her satır için ne yapılacağını hesaplar; veritabanına yazmaz."""
    planlar, gorulen = [], set()
    tcler = {k.tc for k in kayitlar if k.tc}
    personeller = {p.personel_kodu: p for p in Personel.objects.filter(personel_kodu__in=tcler)}
    ogrenciler = {o.tc: o for o in Ogrenci.objects.filter(tc__in=tcler)}
    tcsiz_personel = list(Personel.objects.filter(personel_kodu__isnull=True)) + list(
        Personel.objects.filter(personel_kodu=""))
    tcsiz_ogrenci = list(Ogrenci.objects.filter(tc=""))
    for k in kayitlar:
        p = Plan(k)
        planlar.append(p)
        if k.aktarim:
            p.notlar.append(f"Daha önce aktarıldı ({k.aktarim_notu}).")
            continue
        if not k.tur:
            p.notlar.append("Tür seçilmemiş (personel / öğrenci).")
            continue
        if not tc_gecerli(k.tc):
            p.notlar.append("T.C. kimlik no geçersiz.")
            continue
        if not (k.ad and k.soyad):
            p.notlar.append("Adı ya da soyadı boş.")
            continue
        if (k.tur, k.tc) in gorulen:
            p.notlar.append("Bu T.C. kimlik no listede bir kez daha var; yalnız ilki aktarılır.")
            continue
        gorulen.add((k.tur, k.tc))

        if k.tur == KimlikKaydi.PERSONEL:
            if not personel_yetkisi:
                p.notlar.append("Personel kartlarına aktarma yetkiniz yok (Personel Kartları yöneticisi gerekir).")
                continue
            hedef = personeller.get(k.tc)
            if hedef is not None:
                p.islem, p.hedef = GUNCELLE, hedef
                if ad_anahtari(hedef.ad_soyad) != ad_anahtari(k.ad_soyad):
                    p.notlar.append(f"Kartta “{hedef.ad_soyad}”, kimlikte “{k.ad_soyad}” yazıyor; ad soyad "
                                    f"değiştirilmez, gerekirse karttan düzeltin.")
            else:
                esler = _ad_esler(tcsiz_personel, k)
                if len(esler) == 1:
                    p.islem, p.hedef = GUNCELLE, esler[0]
                    p.notlar.append("T.C. no'su boş olan personel kartıyla ad soyadından eşleşti; T.C. no karta "
                                    "yazılacak.")
                elif len(esler) > 1:
                    p.notlar.append("Aynı adda birden fazla personel kartı var; T.C. no'yu doğru karta elle girin.")
                    continue
                else:
                    p.islem = YENI
                    p.notlar.append("Yeni personel kartı açılır; bölüm, rütbe ve sınıfı karttan tamamlayın.")
            if k.tc in ogrenciler:
                p.notlar.append("Bu T.C. kimlik no öğrenci kaydında da var.")
        else:
            if not ogrenci_yetkisi:
                p.notlar.append("Öğrenci kaydına aktarma yetkiniz yok (Öğrenci Kaydı yöneticisi gerekir).")
                continue
            hedef = ogrenciler.get(k.tc)
            if hedef is None:
                esler = _ad_esler(tcsiz_ogrenci, k)
                hedef = esler[0] if len(esler) == 1 else None
                if hedef is not None:
                    p.notlar.append("T.C. no'su boş olan öğrenci kaydıyla ad soyadından eşleşti.")
            if hedef is not None:
                p.islem, p.hedef = GUNCELLE, hedef
            else:
                p.islem = YENI
                p.notlar.append("Yeni öğrenci kaydı açılır; numara, sınıf ve bölümü kayıttan tamamlayın.")
            if k.tc in personeller:
                p.notlar.append("Bu T.C. kimlik no personel kartlarında da var.")
    return planlar


def _kart_alanlari():
    alanlar = {}
    for ad, tur, secenekler, sira, kayit_alani in KART_ALANLARI:
        a, _ = KartAlani.objects.get_or_create(ad=ad, defaults={"grup": "Kimlik", "tur": tur,
                                                               "secenekler": secenekler, "sira": sira})
        alanlar[kayit_alani] = a
    return alanlar


def _personele_yaz(k, p, alanlar):
    if p is None:
        p = Personel.objects.create(ad_soyad=k.ad_soyad, personel_kodu=k.tc)
    elif not p.personel_kodu:
        p.personel_kodu = k.tc
        p.save(update_fields=["personel_kodu", "guncelleme"])
    for kayit_alani, alan in alanlar.items():
        deger = _kart_degeri(k, kayit_alani)
        if deger:
            KartDegeri.objects.update_or_create(personel=p, alan=alan, defaults={"deger": deger})
    return p


def _ogrenciye_yaz(k, o):
    o = o or Ogrenci()
    for alan in OGRENCI_ALANLARI:
        deger = getattr(k, alan)
        if deger:
            setattr(o, alan, deger)
    o.save()
    return o


def uygula(planlar):
    """Planı uygular (tek işlemde). Dönüş: {"personel": n, "ogrenci": n, "yeni": n}."""
    sayac = {"personel": 0, "ogrenci": 0, "yeni": 0}
    simdi = timezone.now()
    with transaction.atomic():
        alanlar = None
        for p in planlar:
            if not p.aktarilir:
                continue
            k = p.kayit
            if k.tur == KimlikKaydi.PERSONEL:
                alanlar = alanlar or _kart_alanlari()
                hedef = _personele_yaz(k, p.hedef, alanlar)
                k.aktarim_notu = ("Yeni personel kartı: " if p.islem == YENI else "Personel kartı: ") + hedef.ad_soyad
                sayac["personel"] += 1
            else:
                hedef = _ogrenciye_yaz(k, p.hedef)
                k.aktarim_notu = ("Yeni öğrenci kaydı: " if p.islem == YENI else "Öğrenci kaydı: ") + hedef.ad_soyad
                sayac["ogrenci"] += 1
            p.hedef = hedef
            sayac["yeni"] += p.islem == YENI
            k.aktarim = simdi
            k.save(update_fields=["aktarim", "aktarim_notu", "guncelleme"])
    return sayac
