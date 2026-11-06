"""Salon durumu iş kuralları: yetki, çakışma denetimi, kayıt yazma ve takvim özetleri."""

import calendar
import datetime
import uuid
from collections import defaultdict

from django.db import transaction
from django.http import Http404

from core.yetki import DUZENLEME, birim_bul, etkin_yetki

from .models import GUN_BAS, GUN_BIT, Salon, SalonKaydi

BIRIM = "salon-durumu"
EN_COK_TEKRAR = 60  # haftalık tekrarda en fazla bu kadar hafta
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class SalonHatasi(Exception):
    pass


def duzenleyebilir(request):
    """Kayıt girebilir mi? Salon Durumu biriminde Düzenleme yetkisi (üst birimden de gelir) ya da süper kullanıcı."""
    u = request.user
    if not u.is_authenticated:
        return False
    if u.is_superuser:
        return True
    try:
        return etkin_yetki(request, birim_bul(request, BIRIM))[0] >= DUZENLEME
    except Http404:
        return False


def salonlar(sadece_aktif=True):
    qs = Salon.objects.all()
    return list(qs.filter(aktif=True) if sadece_aktif else qs)


def _dk(t):
    return t.hour * 60 + t.minute


def _saat(dk):
    return f"{dk // 60:02d}:{dk % 60:02d}"


def _aralik(tum_gun, bas, bit):
    return (_dk(GUN_BAS), _dk(GUN_BIT)) if tum_gun else (_dk(bas), _dk(bit))


def cakisanlar(salon, tarih, tum_gun, bas, bit, haric=None):
    """O salonda o gün bu saatlerle çakışan kayıtlar."""
    a, b = _aralik(tum_gun, bas, bit)
    qs = SalonKaydi.objects.filter(salon=salon, tarih=tarih)
    if haric is not None:
        qs = qs.exclude(pk=haric)
    out = []
    for k in qs:
        ka, kb = _aralik(k.tum_gun, k.bas, k.bit)
        if k.tum_gun or tum_gun or (ka < b and a < kb):
            out.append(k)
    return out


def _denetle(tum_gun, bas, bit, baslik):
    if not (baslik or "").strip():
        raise SalonHatasi("Başlık yazın (ör. Kısmın dersi).")
    if not tum_gun:
        if bas is None or bit is None:
            raise SalonHatasi("Başlangıç ve bitiş saatini seçin ya da “Tüm gün”ü işaretleyin.")
        if bit <= bas:
            raise SalonHatasi("Bitiş saati başlangıçtan sonra olmalı.")


def tarihler(tarih, tekrar_bitis=None):
    """Kayıt tarihleri: tekrar yoksa yalnız o gün; haftalık tekrarda bitiş tarihine kadar her hafta aynı gün."""
    if tekrar_bitis is None:
        return [tarih]
    if tekrar_bitis < tarih:
        raise SalonHatasi("Tekrarın bitiş tarihi başlangıçtan önce olamaz.")
    out, d = [], tarih
    while d <= tekrar_bitis:
        out.append(d)
        d += datetime.timedelta(days=7)
    if len(out) > EN_COK_TEKRAR:
        raise SalonHatasi(f"Haftalık tekrar en fazla {EN_COK_TEKRAR} hafta olabilir.")
    return out


@transaction.atomic
def ekle(user, salon_listesi, tarih, tum_gun, bas, bit, baslik, aciklama="", tekrar_bitis=None):
    """Seçilen salonlara (haftalık tekrarla birden çok güne) kayıt. Herhangi biri çakışırsa hiçbiri girilmez."""
    _denetle(tum_gun, bas, bit, baslik)
    if not salon_listesi:
        raise SalonHatasi("En az bir salon seçin.")
    gunler = tarihler(tarih, tekrar_bitis)
    cakisma = []
    for s in salon_listesi:
        for g in gunler:
            cakisma += cakisanlar(s, g, tum_gun, bas, bit)
    if cakisma:
        ilk = cakisma[:3]
        metin = "; ".join(f"{k.salon.ad} {k.tarih:%d.%m.%Y} {k.saat_metni} ({k.baslik})" for k in ilk)
        raise SalonHatasi(f"Salon bu saatlerde dolu: {metin}" + (f" ve {len(cakisma) - 3} kayıt daha" if len(cakisma) > 3 else "")
                          + ". Hiçbir kayıt girilmedi.")
    seri = uuid.uuid4() if len(gunler) > 1 else None
    yeni = [SalonKaydi(salon=s, tarih=g, tum_gun=tum_gun, bas=None if tum_gun else bas, bit=None if tum_gun else bit,
                       baslik=baslik.strip()[:120], aciklama=(aciklama or "").strip()[:300], seri=seri,
                       olusturan=user, guncelleyen=user)
            for s in salon_listesi for g in gunler]
    return SalonKaydi.objects.bulk_create(yeni)


@transaction.atomic
def duzenle(user, kayit, salon, tarih, tum_gun, bas, bit, baslik, aciklama=""):
    _denetle(tum_gun, bas, bit, baslik)
    cakisma = cakisanlar(salon, tarih, tum_gun, bas, bit, haric=kayit.pk)
    if cakisma:
        k = cakisma[0]
        raise SalonHatasi(f"Salon bu saatlerde dolu: {k.saat_metni} ({k.baslik}).")
    kayit.salon, kayit.tarih, kayit.tum_gun = salon, tarih, tum_gun
    kayit.bas, kayit.bit = (None, None) if tum_gun else (bas, bit)
    kayit.baslik, kayit.aciklama, kayit.guncelleyen = baslik.strip()[:120], (aciklama or "").strip()[:300], user
    kayit.save()
    return kayit


# ---------------------------------------------------------------- görünüm verisi

def _kayitlar(bas, bit, salon_idleri):
    return list(SalonKaydi.objects.filter(tarih__gte=bas, tarih__lte=bit, salon_id__in=salon_idleri)
                .select_related("salon").order_by("tarih", "-tum_gun", "bas"))


def yil(yil_no, secili, bugun):
    """İphone yıl görünümü gibi 12 ay: [{ay, ad, haftalar: [[{tarih, ay_ici, noktalar, doluluk, bugun}]]}]."""
    ids = [s.pk for s in secili]
    gun_dk = defaultdict(lambda: defaultdict(int))
    for k in _kayitlar(datetime.date(yil_no, 1, 1), datetime.date(yil_no, 12, 31), ids):
        gun_dk[k.tarih][k.salon_id] += k.dakika
    toplam = _dk(GUN_BIT) - _dk(GUN_BAS)
    takvim = calendar.Calendar(firstweekday=0)
    aylar = []
    for ay in range(1, 13):
        haftalar = []
        for hafta in takvim.monthdatescalendar(yil_no, ay):
            satir = []
            for d in hafta:
                dolu = gun_dk.get(d, {})
                oran = max((min(1, dk / toplam) for dk in dolu.values()), default=0)
                satir.append({"tarih": d, "ay_ici": d.month == ay, "bugun": d == bugun, "hs": d.weekday() >= 5,
                              "noktalar": [s for s in secili if dolu.get(s.pk)],
                              "doluluk": 0 if not dolu else (3 if oran >= .75 else 2 if oran >= .35 else 1)})
            haftalar.append(satir)
        aylar.append({"ay": ay, "ad": AYLAR[ay - 1], "haftalar": haftalar,
                      "kayit_gunu": sum(1 for d in gun_dk if d.month == ay)})
    return aylar


def ay(yil_no, ay_no, secili, bugun):
    """Ay görünümü: [[{tarih, ay_ici, bugun, kayitlar}]] (Pazartesi başlar)."""
    haftalar = calendar.Calendar(firstweekday=0).monthdatescalendar(yil_no, ay_no)
    by = defaultdict(list)
    for k in _kayitlar(haftalar[0][0], haftalar[-1][-1], [s.pk for s in secili]):
        by[k.tarih].append(k)
    return [[{"tarih": d, "ay_ici": d.month == ay_no, "bugun": d == bugun, "hs": d.weekday() >= 5,
              "kayitlar": by.get(d, [])} for d in hafta] for hafta in haftalar]


def gun(tarih, secili, simdi=None):
    """Gün görünümü: salon başına kayıtlar (yüzde konumlu bloklar) ve müsait aralıklar."""
    bas_dk, bit_dk = _dk(GUN_BAS), _dk(GUN_BIT)
    boy = bit_dk - bas_dk
    by = defaultdict(list)
    for k in _kayitlar(tarih, tarih, [s.pk for s in secili]):
        by[k.salon_id].append(k)
    sutunlar = []
    for s in secili:
        bloklar, dolu = [], []
        for k in by.get(s.pk, []):
            a, b = _aralik(k.tum_gun, k.bas, k.bit)
            a, b = max(a, bas_dk), min(b, bit_dk)
            if b <= a:
                continue
            dolu.append((a, b))
            bloklar.append({"kayit": k, "ust": round((a - bas_dk) * 100 / boy, 3), "boy": round((b - a) * 100 / boy, 3)})
        musait, imlec = [], bas_dk
        for a, b in sorted(dolu):
            if a > imlec:
                musait.append((imlec, a))
            imlec = max(imlec, b)
        if imlec < bit_dk:
            musait.append((imlec, bit_dk))
        durum = None
        if simdi is not None and simdi.date() == tarih:
            sdk = simdi.hour * 60 + simdi.minute
            su_an = next((x["kayit"] for x in bloklar if _aralik(x["kayit"].tum_gun, x["kayit"].bas, x["kayit"].bit)[0] <= sdk
                          < _aralik(x["kayit"].tum_gun, x["kayit"].bas, x["kayit"].bit)[1]), None)
            durum = {"dolu": su_an is not None, "kayit": su_an}
        sutunlar.append({"salon": s, "bloklar": bloklar, "durum": durum,
                         "musait": [{"bas": _saat(a), "bit": _saat(b), "ust": round((a - bas_dk) * 100 / boy, 3),
                                     "boy": round((b - a) * 100 / boy, 3), "uzun": b - a >= 60} for a, b in musait]})
    saatler = [{"saat": f"{h:02d}:00", "ust": round((h * 60 - bas_dk) * 100 / boy, 3)}
               for h in range(GUN_BAS.hour, GUN_BIT.hour + 1)]
    return sutunlar, saatler


def simdiki_durum(secili, simdi):
    """Her salonun şu anki durumu: dolu (hangi kayıt, ne zamana kadar) ya da müsait (sıradaki kayıt)."""
    bugun = simdi.date()
    sdk = simdi.hour * 60 + simdi.minute
    by = defaultdict(list)
    for k in _kayitlar(bugun, bugun, [s.pk for s in secili]):
        by[k.salon_id].append(k)
    out = []
    for s in secili:
        su_an = siradaki = None
        for k in by.get(s.pk, []):
            a, b = _aralik(k.tum_gun, k.bas, k.bit)
            if a <= sdk < b:
                su_an = k
            elif a > sdk and (siradaki is None or a < _aralik(siradaki.tum_gun, siradaki.bas, siradaki.bit)[0]):
                siradaki = k
        out.append({"salon": s, "su_an": su_an, "siradaki": siradaki})
    return out
