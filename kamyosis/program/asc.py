"""aSc Timetables 2012 XML içe aktarımı.

Tanımlar aSc kimliğiyle (yoksa koda/ada göre) güncellenir; program her seferinde
yeni bir taslak sürüm olarak oluşturulur. Öğretmenler, adı birebir eşleşen
personele otomatik bağlanır; kalanlar eşleştirme ekranına düşer.
"""

import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal

from django.db import transaction

from personel.models import Bolum, Personel

from .models import (
    Ders, DersSaati, Derslik, Grup, HaftalikDers, Kisim, ProgramHucresi, ProgramOgretmeni, ProgramSurumu,
)


class AscHatasi(Exception):
    pass


@dataclass
class Rapor:
    sayilar: dict = field(default_factory=dict)
    uyarilar: list = field(default_factory=list)


def ad_anahtari(ad):
    """Karşılaştırma için ad: Türkçe büyük/küçük harf ve aksan farkları yok sayılır."""
    s = (ad or "").replace("İ", "i").replace("I", "ı").lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ı", "i")
    return " ".join(s.split())


def _ids(deger):
    return [x for x in (deger or "").split(",") if x]


def _saat(deger):
    m = re.match(r"^\s*(\d{1,2}):(\d{2})", deger or "")
    return time(int(m.group(1)), int(m.group(2))) if m else None


def _kapasite(deger):
    return int(deger) if (deger or "").isdigit() else None


def ders_kodu_parcalari(kod):
    """"BİL103" → ("BİL", 1). Rakam yoksa sınıf None."""
    m = re.match(r"^(\D+?)\s*(\d)", kod or "")
    if m:
        return m.group(1).strip(), int(m.group(2))
    return (kod or "").strip(), None


def kisim_bolum_kodu(kisa):
    """"1SVN" → "SVN"."""
    return re.sub(r"^\d+", "", kisa or "").strip()


def kisim_turu(kod, ad=""):
    """Kısım adından tür: "Kr.Tm.İşl." → kredi tamamlama, "Hazırlık 1" → hazırlık."""
    anahtar = ad_anahtari(f"{kod} {ad}")
    if "hazirlik" in anahtar:
        return Kisim.HAZIRLIK
    if anahtar.startswith("kr.") or "kredi" in anahtar:
        return Kisim.KREDI
    return Kisim.NORMAL


def _bolum_onekleri():
    """{önek: Bolum}; bölüm kısa kodları ve "ek ders kodu önekleri"."""
    sonuc = {}
    for b in Bolum.objects.filter(aktif=True):
        for o in b.onekler:
            sonuc.setdefault(o.upper(), b)
    return sonuc


def tanimlari_guncelle(surum):
    """Ders/kısım bölümleri, kısım türü ve sınıfı, öğretmenlerin tahmini bölümü; boş personel bölümleri.

    Koddan çıkarılamayan bilgiler (ör. yönetim panelinden elle girilen bölüm) korunur.
    """
    onekler = _bolum_onekleri()
    for d in Ders.objects.all():
        b = onekler.get(ders_kodu_parcalari(d.kod)[0].upper())
        if b is not None and d.bolum_id != b.pk:
            d.bolum = b
            d.save(update_fields=["bolum"])

    for k in Kisim.objects.filter(haftalik_dersler__surum=surum).distinct():
        tur = kisim_turu(k.kod, k.ad)
        if k.tur == Kisim.NORMAL and tur != Kisim.NORMAL:
            k.tur = tur
        if k.tur == Kisim.NORMAL:
            b = onekler.get(kisim_bolum_kodu(k.kod).upper())
        elif k.tur == Kisim.KREDI:  # "Kr.Tm.İşl." → İŞL
            buyuk = k.kod.replace("i", "İ").upper()
            b = next((b for o, b in onekler.items() if o in buyuk), None)
        else:
            b = None
        if b is not None:
            k.bolum = b
        if k.tur == Kisim.HAZIRLIK:
            k.sinif = None
        else:
            sayac = Counter(hd.ders.sinif for hd in k.haftalik_dersler.filter(surum=surum).select_related("ders") if hd.ders.sinif)
            k.sinif = sayac.most_common(1)[0][0] if sayac else None
        k.save(update_fields=["tur", "bolum", "sinif"])

    # Öğretmenin tahmini bölümü: en çok saat verdiği derslerin bölümü
    saatler = {}
    for hd in HaftalikDers.objects.filter(surum=surum).select_related("ders").prefetch_related("ogretmenler"):
        if hd.ders.bolum_id:
            for o in hd.ogretmenler.all():
                saatler.setdefault(o.pk, Counter())[hd.ders.bolum_id] += float(hd.haftalik_saat)
    for o in ProgramOgretmeni.objects.filter(haftalik_dersler__surum=surum).distinct().select_related("personel"):
        sayac = saatler.get(o.pk)
        yeni = sayac.most_common(1)[0][0] if sayac else None
        if o.tahmini_bolum_id != yeni:
            o.tahmini_bolum_id = yeni
            o.save(update_fields=["tahmini_bolum"])
        if o.personel is not None and o.personel.bolum_id is None and yeni is not None:
            o.personel.bolum_id = yeni
            o.personel.save(update_fields=["bolum"])


def _bul_veya_yeni(model, asc_id, **yedek_anahtar):
    """Önce aSc kimliğiyle, bulunamazsa yedek anahtarla bulur; yoksa kaydedilmemiş yeni nesne döner."""
    nesne = model.objects.filter(asc_id=asc_id).first() if asc_id else None
    if nesne is None and yedek_anahtar:
        nesne = model.objects.filter(**yedek_anahtar).first()
    if nesne is None:
        nesne = model(**yedek_anahtar)
    if asc_id:
        nesne.asc_id = asc_id
    return nesne


@transaction.atomic
def ice_aktar(kaynak, *, surum_adi, kaynak_dosya="", kullanici=None):
    """XML'i (dosya yolu veya dosya nesnesi) okuyup yeni bir taslak ProgramSurumu oluşturur."""
    try:
        kok = ET.parse(kaynak).getroot()
    except ET.ParseError as e:
        raise AscHatasi(f"XML okunamadı: {e}") from e
    if kok.tag != "timetable":
        raise AscHatasi("Bu dosya bir aSc Timetables XML dosyası değil.")

    def liste(etiket):
        el = kok.find(etiket)
        return list(el) if el is not None else []

    rapor = Rapor()

    # --- derslikler
    derslikler = {}
    for r in liste("classrooms"):
        d = _bul_veya_yeni(Derslik, r.get("id"), ad=(r.get("name") or r.get("short")).strip())
        d.ad = (r.get("name") or r.get("short")).strip()
        d.kapasite = _kapasite(r.get("capacity"))
        d.save()
        derslikler[r.get("id")] = d

    # --- dersler
    dersler = {}
    for r in liste("subjects"):
        kod = (r.get("short") or r.get("name")).strip()
        _, sinif = ders_kodu_parcalari(kod)
        d = _bul_veya_yeni(Ders, r.get("id"), kod=kod)
        d.kod, d.ad, d.sinif = kod, (r.get("name") or kod).strip(), sinif
        d.save()
        dersler[r.get("id")] = d

    # --- kısımlar ve gruplar
    kisimlar = {}
    for r in liste("classes"):
        kod = (r.get("short") or r.get("name")).strip()
        k = _bul_veya_yeni(Kisim, r.get("id"), kod=kod)
        k.kod, k.ad = kod, (r.get("name") or kod).strip()
        k.save()
        kisimlar[r.get("id")] = k
    gruplar = {}
    for r in liste("groups"):
        kisim = kisimlar.get(r.get("classid"))
        if kisim is None:
            continue
        ad = (r.get("name") or "").strip() or "Grup"
        g = _bul_veya_yeni(Grup, r.get("id"), kisim=kisim, ad=ad)
        g.kisim, g.ad = kisim, ad
        g.tum_kisim = r.get("entireclass") == "1"
        g.bolunme = r.get("divisiontag") or ""
        g.save()
        gruplar[r.get("id")] = g

    # --- öğretmenler (otomatik eşleşme: ad birebir aynıysa)
    personel_adlari = {}
    for p in Personel.objects.all():
        personel_adlari.setdefault(ad_anahtari(p.ad_soyad), p)
    ogretmenler = {}
    otomatik = 0
    for r in liste("teachers"):
        ad = (r.get("name") or " ".join(filter(None, [r.get("firstname"), r.get("lastname")])) or r.get("short") or "").strip()
        o = _bul_veya_yeni(ProgramOgretmeni, r.get("id"), ad=ad)
        o.ad, o.kisa_ad = ad, (r.get("short") or "").strip()
        if o.durum == ProgramOgretmeni.BEKLIYOR and o.personel_id is None:
            p = personel_adlari.get(ad_anahtari(ad))
            if p is not None:
                o.personel, o.durum = p, ProgramOgretmeni.OTOMATIK
                otomatik += 1
        o.save()
        ogretmenler[r.get("id")] = o

    # --- sürüm, ders saatleri
    surum = ProgramSurumu.objects.create(ad=surum_adi, kaynak_dosya=kaynak_dosya, yukleyen=kullanici)
    for r in liste("periods"):
        no = r.get("period")
        if no and no.isdigit():
            DersSaati.objects.create(surum=surum, no=int(no), baslangic=_saat(r.get("starttime")), bitis=_saat(r.get("endtime")))

    # --- haftalık dersler
    haftalik = {}
    for r in liste("lessons"):
        ders = dersler.get(r.get("subjectid"))
        if ders is None:
            rapor.uyarilar.append(f"Dersi bilinmeyen kayıt atlandı (aSc {r.get('id')}).")
            continue
        saat = Decimal(r.get("periodsperweek") or "0")
        hd = HaftalikDers.objects.create(
            surum=surum, ders=ders, haftalik_saat=saat,
            blok=int(r.get("durationperiods") or r.get("periodspercard") or 1), asc_id=r.get("id") or "",
        )
        hd.kisimlar.set([kisimlar[i] for i in _ids(r.get("classids")) if i in kisimlar])
        hd.gruplar.set([gruplar[i] for i in _ids(r.get("groupids")) if i in gruplar and not gruplar[i].tum_kisim])
        ogr = [ogretmenler[i] for i in _ids(r.get("teacherids")) if i in ogretmenler]
        hd.ogretmenler.set(ogr)
        haftalik[r.get("id")] = hd

    # --- program hücreleri
    hucreler = []
    for r in liste("cards"):
        hd = haftalik.get(r.get("lessonid"))
        saat = r.get("period")
        if hd is None or not (saat or "").isdigit():
            rapor.uyarilar.append(f"Yerleşimi okunamayan kart atlandı (ders {r.get('lessonid')}).")
            continue
        derslik_idleri = _ids(r.get("classroomids"))
        derslik = derslikler.get(derslik_idleri[0]) if derslik_idleri else None
        for i, bit in enumerate(r.get("days") or "", start=1):
            if bit == "1":
                hucreler.append(ProgramHucresi(surum=surum, haftalik_ders=hd, gun=i, saat=int(saat), derslik=derslik))
    ProgramHucresi.objects.bulk_create(hucreler)
    tanimlari_guncelle(surum)

    bekleyen = ProgramOgretmeni.objects.filter(pk__in=[o.pk for o in ogretmenler.values()], durum=ProgramOgretmeni.BEKLIYOR).count()
    rapor.sayilar = {
        "Derslik": len(derslikler), "Ders": len(dersler), "Kısım": len(kisimlar), "Grup": len(gruplar),
        "Öğretmen": len(ogretmenler), "Haftalık ders": len(haftalik), "Yerleşmiş ders saati": len(hucreler),
        "Bu yüklemede otomatik eşleşen öğretmen": otomatik, "Eşleştirme bekleyen öğretmen": bekleyen,
    }
    return surum, rapor
