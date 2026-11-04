"""Personel yoklaması iş kuralları.

Yetki ("Personel Yoklaması" birimi, İdari İşler altında):
- Görüntüleme: yoklamayı ve personel kartını görür.
- Düzenleme: kayıt ekler / düzenler / siler, fotoğraf yükler, günün yoklamasını verir.
- Yönetim + tüm bölümler (idari işler yetkilisi) ve sistem yöneticileri: herkesi görür, rapor alır, izin türlerini
  yönetir, toplu fotoğraf yükler.
Bölüm kapsamlı kullanıcı yalnızca kendi bölümünün personelini görür ve girer.

Eşzamanlı giriş: her kayıt ayrı ve kısa bir işlemde yazılır (SQLite IMMEDIATE + WAL, yazmalar sıraya girer).
Çakışma denetimi aynı işlemin içindedir; düzenlemede sürüm (iyimser kilit) karşılaştırılır: iki kişi aynı kaydı
aynı anda değiştirirse ikincisi uyarı alır, kimsenin değişikliği sessizce ezilmez.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from personel.models import Bolum, Personel

from .models import GunlukOnay, IzinTuru, YoklamaGecmisi, YoklamaKaydi

BIRIM = "personel-yoklamasi"
# Bölüm hesapları geçmiş günlere kayıt giremez; bugüne ait kayıt bu saate kadar girilir. Bölüm günün yoklamasını
# kesinleştirince o güne değen kayıtları artık yalnız idari işler yetkilisi değiştirebilir.
GIRIS_SON_SAAT = getattr(settings, "YOKLAMA_GIRIS_SON_SAAT", datetime.time(9, 0))
EN_UZUN_ARALIK = 62  # gün (görünüm ve rapor)


class YoklamaHatasi(Exception):
    pass


@dataclass
class YoklamaYetkisi:
    goruntule: bool = False
    giris: bool = False
    yonetim: bool = False          # idari işler yetkilisi: tüm bölümler + yönetim
    kapsam_bolum: object = None    # None = tüm bölümler

    def kapsar(self, bolum_id):
        return self.kapsam_bolum is None or bolum_id == self.kapsam_bolum.pk


def yetki(request):
    if hasattr(request, "_yoklama_yetkisi"):
        return request._yoklama_yetkisi
    y = YoklamaYetkisi()
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule, y.giris = seviye >= GORUNTULEME, seviye >= DUZENLEME
    if kapsam == Yetki.BOLUM:
        y.kapsam_bolum = request.user.bolum
        if y.kapsam_bolum is None:
            y.goruntule = y.giris = False
    else:
        y.yonetim = seviye >= YONETIM
    request._yoklama_yetkisi = y
    return y


def personeller(y, bolum=None):
    qs = Personel.objects.filter(aktif=True).select_related("bolum", "unvan", "rutbe", "sinif")
    if y.kapsam_bolum is not None:
        qs = qs.filter(bolum=y.kapsam_bolum)
    elif bolum is not None:
        qs = qs.filter(bolum=bolum)
    return qs.order_by("bolum__ad", "ad_soyad")


def kapsamdaki_personel(y, pk):
    p = Personel.objects.filter(pk=pk).select_related("bolum", "unvan", "rutbe", "sinif").first()
    if p is None or not y.goruntule or not y.kapsar(p.bolum_id):
        raise Http404("Personel bulunamadı.")
    return p


def bolumler(y):
    if y.kapsam_bolum is not None:
        return [y.kapsam_bolum]
    return list(Bolum.objects.filter(aktif=True, personeller__aktif=True).distinct().order_by("ad"))


# ---------------------------------------------------------------- zaman

def gun_araligi(tarih):
    """Günün yerel 00:00 – ertesi gün 00:00 aralığı (saat dilimi bilgili)."""
    tz = timezone.get_current_timezone()
    bas = timezone.make_aware(datetime.datetime.combine(tarih, datetime.time()), tz)
    return bas, timezone.make_aware(datetime.datetime.combine(tarih + datetime.timedelta(days=1), datetime.time()), tz)


def aralik(tam_gun, bas_tarih, bit_tarih=None, bas_saat=None, bit_saat=None):
    """Formdan kayıt aralığı. Tam gün: bas_tarih 00:00 – bit_tarih ertesi 00:00. Saatlik: bas_tarih bas_saat – bit_saat."""
    tz = timezone.get_current_timezone()
    if bas_tarih is None:
        raise YoklamaHatasi("Başlangıç tarihini seçin.")
    if tam_gun:
        bit_tarih = bit_tarih or bas_tarih
        if bit_tarih < bas_tarih:
            raise YoklamaHatasi("Bitiş tarihi başlangıçtan önce olamaz.")
        if (bit_tarih - bas_tarih).days > 366:
            raise YoklamaHatasi("Bir kayıt en fazla bir yıl sürebilir.")
        return gun_araligi(bas_tarih)[0], gun_araligi(bit_tarih)[1]
    if bas_saat is None or bit_saat is None:
        raise YoklamaHatasi("Başlangıç ve bitiş saatini seçin.")
    bas = timezone.make_aware(datetime.datetime.combine(bas_tarih, bas_saat), tz)
    bit = timezone.make_aware(datetime.datetime.combine(bit_tarih or bas_tarih, bit_saat), tz)
    if bit <= bas:
        raise YoklamaHatasi("Bitiş saati başlangıçtan sonra olmalı.")
    return bas, bit


# ---------------------------------------------------------------- günün yoklaması

def kayitlar(personel_idleri, bas, bit):
    """Aralığa değen kayıtlar (personel ve türüyle)."""
    return list(YoklamaKaydi.objects.filter(personel_id__in=personel_idleri, baslangic__lt=bit, bitis__gt=bas)
                .select_related("tur", "personel", "olusturan").order_by("baslangic"))


@dataclass
class KisiDurumu:
    personel: Personel
    kayitlar: list
    gun_boyu: bool          # gün boyu yok (tam gün kaydı ya da günü kaplayan kayıt)

    @property
    def mevcut(self):
        return not self.kayitlar

    @property
    def kismi(self):
        return bool(self.kayitlar) and not self.gun_boyu


def gun_durumu(tarih, kisiler):
    """[KisiDurumu] — kişilerin o günkü durumu."""
    bas, bit = gun_araligi(tarih)
    by = defaultdict(list)
    for k in kayitlar([p.pk for p in kisiler], bas, bit):
        by[k.personel_id].append(k)
    out = []
    for p in kisiler:
        ks = by.get(p.pk, [])
        out.append(KisiDurumu(p, ks, any(k.baslangic <= bas and k.bitis >= bit for k in ks)))
    return out


def ozet(durumlar):
    """Sayılar: toplam, mevcut, gün boyu yok, kısmi ve türlere göre (gün boyu ve kısmi birlikte)."""
    turler = defaultdict(lambda: {"tur": None, "sayi": 0})
    for d in durumlar:
        for t in {k.tur_id: k.tur for k in d.kayitlar}.values():
            turler[t.pk]["tur"] = t
            turler[t.pk]["sayi"] += 1
    return {
        "toplam": len(durumlar), "mevcut": sum(d.mevcut for d in durumlar),
        "gun_boyu": sum(d.gun_boyu for d in durumlar), "kismi": sum(d.kismi for d in durumlar),
        "turler": sorted(turler.values(), key=lambda t: (t["tur"].sira, t["tur"].ad)),
    }


def takvim(bas_tarih, bit_tarih, kisiler, hepsi=False):
    """Aralık görünümü: günler ve kişi satırları [{personel, hucreler: [{tarih, kayitlar, gun_boyu}]}]."""
    gunler = [bas_tarih + datetime.timedelta(days=i) for i in range((bit_tarih - bas_tarih).days + 1)]
    bas, bit = gun_araligi(bas_tarih)[0], gun_araligi(bit_tarih)[1]
    by = defaultdict(list)
    for k in kayitlar([p.pk for p in kisiler], bas, bit):
        by[k.personel_id].append(k)
    satirlar, gunluk = [], {g: {"yok": 0, "kismi": 0} for g in gunler}
    for p in kisiler:
        ks = by.get(p.pk, [])
        if not ks and not hepsi:
            continue
        hucreler = []
        for g in gunler:
            gb, gs = gun_araligi(g)
            hk = [k for k in ks if k.baslangic < gs and k.bitis > gb]
            tam = any(k.baslangic <= gb and k.bitis >= gs for k in hk)
            if hk:
                gunluk[g]["yok" if tam else "kismi"] += 1
            hucreler.append({"tarih": g, "kayitlar": hk, "gun_boyu": tam})
        satirlar.append({"personel": p, "hucreler": hucreler, "kayit_sayisi": len(ks)})
    toplam = len(kisiler)
    gun_ozet = [{"tarih": g, "yok": gunluk[g]["yok"], "kismi": gunluk[g]["kismi"], "mevcut": toplam - gunluk[g]["yok"]}
                for g in gunler]
    return gunler, satirlar, gun_ozet


# ---------------------------------------------------------------- kayıt yazma

def _ozet_metni(k):
    return f"{k.tur.ad}: {k.aralik_metni}" + (f" — {k.aciklama}" if k.aciklama else "")


def _onaylari_isaretle(personel, bas, bit):
    """Kaydın değdiği ve yoklaması verilmiş günleri "onaydan sonra değişti" diye işaretler. Dönüş: işaretlenen var mı."""
    if personel.bolum_id is None:
        return False
    ilk, son = timezone.localtime(bas).date(), timezone.localtime(bit - datetime.timedelta(microseconds=1)).date()
    return bool(GunlukOnay.objects.filter(bolum_id=personel.bolum_id, tarih__range=(ilk, son))
                .update(degisti=timezone.now()))


def _simdi():
    return timezone.localtime()


def ilk_giris_tarihi():
    """Bölüm hesabının kayıt başlatabileceği ilk gün: saat 09:00'dan önce bugün, sonra yarın."""
    simdi = _simdi()
    return simdi.date() if simdi.time() < GIRIS_SON_SAAT else simdi.date() + datetime.timedelta(days=1)


def _gunler(bas, bit):
    return timezone.localtime(bas).date(), timezone.localtime(bit - datetime.timedelta(microseconds=1)).date()


def kesinlesen_gunler(bolum_id, bas, bit):
    if bolum_id is None:
        return []
    return list(GunlukOnay.objects.filter(bolum_id=bolum_id, tarih__range=_gunler(bas, bit))
                .order_by("tarih").values_list("tarih", flat=True))


def kilit_nedeni(y, personel, bas, bit):
    """Bölüm hesabı bu aralığa değen bir kaydı ekleyemez / değiştiremez / silemezse nedeni (yoksa None).
    İdari işler yetkilisi (ve sistem yöneticisi) kilitlerden etkilenmez."""
    if y.yonetim:
        return None
    ilk_gun = _gunler(bas, bit)[0]
    simdi = _simdi()
    if ilk_gun < simdi.date():
        return "Geçmiş günlerin yoklaması değiştirilemez. Düzeltme için idari işler yetkilisine başvurun."
    if ilk_gun < ilk_giris_tarihi():
        return (f"Bugünün yoklaması saat {GIRIS_SON_SAAT:%H:%M}'a kadar girilebilir; bugüne değen kayıtları artık "
                "yalnız idari işler yetkilisi değiştirebilir. Yarından başlayan kayıt girebilirsiniz.")
    kesin = kesinlesen_gunler(personel.bolum_id, bas, bit)
    if kesin:
        gunler = ", ".join(f"{g:%d.%m.%Y}" for g in kesin[:5]) + (" …" if len(kesin) > 5 else "")
        return (f"{gunler} yoklaması kesinleşti; bu günlere değen kayıtları yalnız idari işler yetkilisi "
                "değiştirebilir.")
    return None


def kayit_kilitli_mi(y, kayit):
    return kilit_nedeni(y, kayit.personel, kayit.baslangic, kayit.bitis) is not None


def gun_kilidi(y, bolum_id, tarih):
    """Bölüm hesabı bu güne kayıt giremiyorsa nedeni (ekranlarda düğmeleri kapatmak için)."""
    bas, bit = gun_araligi(tarih)
    return kilit_nedeni(y, type("P", (), {"bolum_id": bolum_id})(), bas, bit)


def _kilit_denetle(y, personel, bas, bit):
    neden = kilit_nedeni(y, personel, bas, bit)
    if neden:
        raise YoklamaHatasi(neden)


def _cakisma(personel, bas, bit, haric=None):
    qs = YoklamaKaydi.objects.filter(personel=personel, baslangic__lt=bit, bitis__gt=bas).select_related("tur")
    if haric is not None:
        qs = qs.exclude(pk=haric)
    return qs.first()


def _denetle(y, personel, tur):
    if not y.giris or not y.kapsar(personel.bolum_id):
        raise YoklamaHatasi("Bu personel için yoklama girme yetkiniz yok.")
    if not personel.aktif:
        raise YoklamaHatasi("Pasif personele kayıt girilemez.")
    if tur is None or not tur.aktif:
        raise YoklamaHatasi("Geçerli bir izin türü seçin.")


@transaction.atomic
def ekle(user, y, personel, tur, bas, bit, aciklama=""):
    _denetle(y, personel, tur)
    _kilit_denetle(y, personel, bas, bit)
    diger = _cakisma(personel, bas, bit)
    if diger is not None:
        raise YoklamaHatasi(f"Bu aralıkta zaten bir kayıt var: {diger.tur.ad}, {diger.aralik_metni}. "
                            "Önce onu düzenleyin ya da silin.")
    k = YoklamaKaydi.objects.create(personel=personel, tur=tur, baslangic=bas, bitis=bit,
                                    aciklama=(aciklama or "").strip()[:300], olusturan=user, guncelleyen=user)
    sonrasi = _onaylari_isaretle(personel, bas, bit)
    YoklamaGecmisi.objects.create(personel=personel, kayit_id=k.pk, islem=YoklamaGecmisi.EKLE, ozet=_ozet_metni(k)[:400],
                                  kullanici=user, onay_sonrasi=sonrasi)
    return k


@transaction.atomic
def duzenle(user, y, kayit_id, okunan_surum, tur, bas, bit, aciklama=""):
    k = YoklamaKaydi.objects.select_related("personel", "tur").filter(pk=kayit_id).first()
    if k is None:
        raise YoklamaHatasi("Kayıt bu sırada silinmiş; sayfayı yenileyin.")
    _denetle(y, k.personel, tur)
    _kilit_denetle(y, k.personel, k.baslangic, k.bitis)
    _kilit_denetle(y, k.personel, bas, bit)
    if okunan_surum != k.surum:
        raise YoklamaHatasi("Bu kayıt siz düzenlerken başka bir kullanıcı tarafından değiştirildi. Sayfayı yenileyip "
                            "tekrar deneyin.")
    diger = _cakisma(k.personel, bas, bit, haric=k.pk)
    if diger is not None:
        raise YoklamaHatasi(f"Bu aralıkta başka bir kayıt var: {diger.tur.ad}, {diger.aralik_metni}.")
    eski_bas, eski_bit = k.baslangic, k.bitis
    guncellenen = YoklamaKaydi.objects.filter(pk=k.pk, surum=okunan_surum).update(
        tur=tur, baslangic=bas, bitis=bit, aciklama=(aciklama or "").strip()[:300], guncelleyen=user,
        guncelleme=timezone.now(), surum=F("surum") + 1)
    if not guncellenen:
        raise YoklamaHatasi("Bu kayıt siz düzenlerken değiştirildi; sayfayı yenileyin.")
    k.refresh_from_db()
    sonrasi = _onaylari_isaretle(k.personel, min(eski_bas, bas), max(eski_bit, bit))
    YoklamaGecmisi.objects.create(personel=k.personel, kayit_id=k.pk, islem=YoklamaGecmisi.DUZENLE,
                                  ozet=_ozet_metni(k)[:400], kullanici=user, onay_sonrasi=sonrasi)
    return k


@transaction.atomic
def sil(user, y, kayit_id):
    k = YoklamaKaydi.objects.select_related("personel", "tur").filter(pk=kayit_id).first()
    if k is None:
        return None
    if not y.giris or not y.kapsar(k.personel.bolum_id):
        raise YoklamaHatasi("Bu kaydı silme yetkiniz yok.")
    _kilit_denetle(y, k.personel, k.baslangic, k.bitis)
    ozet_ = _ozet_metni(k)
    personel, bas, bit = k.personel, k.baslangic, k.bitis
    k.delete()
    sonrasi = _onaylari_isaretle(personel, bas, bit)
    YoklamaGecmisi.objects.create(personel=personel, kayit_id=kayit_id, islem=YoklamaGecmisi.SIL, ozet=ozet_[:400],
                                  kullanici=user, onay_sonrasi=sonrasi)
    return personel


# ---------------------------------------------------------------- günlük onay

def onay_yetkisi(y, bolum):
    return y.giris and y.kapsar(bolum.pk)


@transaction.atomic
def onayla(user, y, bolum, tarih):
    if not onay_yetkisi(y, bolum):
        raise YoklamaHatasi("Bu bölümün yoklamasını verme yetkiniz yok.")
    onay, yeni = GunlukOnay.objects.get_or_create(bolum=bolum, tarih=tarih, defaults={"onaylayan": user})
    if not yeni:  # yeniden kesinleştirildi: "değişti" işareti kalkar
        GunlukOnay.objects.filter(pk=onay.pk).update(onaylayan=user, zaman=timezone.now(), degisti=None)
    return onay


def onay_tablosu(tarih, bolum_listesi):
    """[{bolum, onay, toplam, mevcut, yok}] — idari işler için günün bölüm bölüm durumu."""
    onaylar = {o.bolum_id: o for o in GunlukOnay.objects.filter(tarih=tarih, bolum__in=bolum_listesi).select_related("onaylayan")}
    kisiler = list(Personel.objects.filter(aktif=True, bolum__in=bolum_listesi).select_related("bolum"))
    durum = gun_durumu(tarih, kisiler)
    by = defaultdict(list)
    for d in durum:
        by[d.personel.bolum_id].append(d)
    out = []
    for b in bolum_listesi:
        ds = by.get(b.pk, [])
        out.append({"bolum": b, "onay": onaylar.get(b.pk), "toplam": len(ds), "mevcut": sum(d.mevcut for d in ds),
                    "gun_boyu": sum(d.gun_boyu for d in ds), "kismi": sum(d.kismi for d in ds)})
    return out


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    from django.urls import reverse

    y = yetki(request)
    if not y.giris:
        return []
    bugun = timezone.localdate()
    if y.kapsam_bolum is not None:
        if GunlukOnay.objects.filter(bolum=y.kapsam_bolum, tarih=bugun).exists():
            return []
        return [{"renk": "eksik", "ikon": "person-check", "sayi": None, "ad": "Bugünün personel yoklaması kesinleştirilmedi",
                 "aciklama": f"{y.kapsam_bolum.ad} · {bugun:%d.%m.%Y}", "url": reverse("yoklama:ana")}]
    if not y.yonetim:
        return []
    liste = bolumler(y)
    verilen = set(GunlukOnay.objects.filter(tarih=bugun, bolum__in=liste).values_list("bolum_id", flat=True))
    eksik = sum(1 for b in liste if b.pk not in verilen)
    if not eksik:
        return []
    return [{"renk": "bekliyor", "ikon": "person-check", "sayi": eksik, "ad": "Yoklamayı kesinleştirmeyen bölüm",
             "aciklama": f"Bugün · {bugun:%d.%m.%Y}", "url": reverse("yoklama:ana")}]


def izin_turleri(sadece_aktif=True):
    qs = IzinTuru.objects.all()
    return qs.filter(aktif=True) if sadece_aktif else qs
