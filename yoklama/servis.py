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

from .birim import BIRIMSIZ, Agac
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
    yonetim: bool = False          # tüm okul + yönetim (idari işler yetkilisi, sistem yöneticisi)
    kapsam_birim: object = None    # None = tüm okul; yoksa hesabın teşkilat birimi (alt birimleriyle)
    kapsam_idler: object = None    # kapsam biriminin ve alt birimlerinin kimlikleri
    agac: object = None

    @property
    def tum_okul(self):
        return self.kapsam_idler is None

    def kapsar_birim(self, pk):
        return self.kapsam_idler is None or pk in self.kapsam_idler

    def kapsar(self, personel):
        return self.kapsar_birim(self.agac.kisi_birimi(personel))


def yetki(request):
    """Hesabın yoklama yetkisi. Tüm okul: kapsamı "tüm bölümler" olanlar (idari işler yetkilisi, sistem
    yöneticileri). Diğerleri: teşkilat birimi (yoksa bölümünün birimi) ve alt birimleri."""
    if hasattr(request, "_yoklama_yetkisi"):
        return request._yoklama_yetkisi
    y = YoklamaYetkisi(agac=Agac())
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule, y.giris = seviye >= GORUNTULEME, seviye >= DUZENLEME
    if kapsam == Yetki.BOLUM:
        u = request.user
        b = y.agac.birimler.get(getattr(u, "teskilat_birimi_id", None)) or y.agac.bolumun(getattr(u, "bolum_id", None))
        if b is None:  # birimi belirsiz hesap hiçbir şeyi kapsamaz
            y.goruntule = y.giris = False
            y.kapsam_idler = set()
        else:
            y.kapsam_birim, y.kapsam_idler = b, y.agac.alt_idler(b.pk)
    else:
        y.yonetim = seviye >= YONETIM
    request._yoklama_yetkisi = y
    return y


def personeller(y, birim=None, alt=True):
    """Kapsamdaki aktif personel; birim verilirse o birim (alt=True: alt birimleriyle)."""
    qs = Personel.objects.filter(aktif=True).select_related("bolum", "unvan", "rutbe", "sinif", "teskilat_birimi")
    if birim is not None:
        idler = y.agac.alt_idler(birim.pk) if (alt and birim.pk) else {birim.pk}
        if y.kapsam_idler is not None:
            idler &= y.kapsam_idler
        qs = qs.filter(y.agac.kosul(idler))
    elif y.kapsam_idler is not None:
        qs = qs.filter(y.agac.kosul(y.kapsam_idler))
    return qs.order_by("ad_soyad")


def kapsamdaki_personel(y, pk):
    p = Personel.objects.filter(pk=pk).select_related("bolum", "unvan", "rutbe", "sinif", "teskilat_birimi").first()
    if p is None or not y.goruntule or not y.kapsar(p):
        raise Http404("Personel bulunamadı.")
    return p


def birim_secenekleri(y):
    """Seçim kutusu için kapsamdaki birimler [(birim, derinlik)] — personeli olan dallar."""
    kokler = [y.kapsam_birim.pk] if y.kapsam_birim is not None else None
    sayilar = defaultdict(int)
    for p in personeller(y):
        for b in y.agac.zincir(y.agac.kisi_birimi(p)):
            sayilar[b.pk] += 1
    out = [(b, d) for b, d in y.agac.sirali(kokler) if sayilar.get(b.pk)]
    if y.tum_okul and personeller(y, BIRIMSIZ).exists():
        out.append((BIRIMSIZ, 0))
    return out


def birim_basligi(birim):
    """Raporlarda: "Askeri Bilimler Bölümü", "İdari İşler Şube Müdürlüğü" …"""
    if birim is None:
        return ""
    return f"{birim.ad} Bölümü" if birim.tur == "bolum" and not birim.ad.endswith("Bölümü") else birim.ad


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


def _onaylari_isaretle(y, personel, bas, bit):
    """Kaydın değdiği ve kesinleşmiş günleri "kesinleştikten sonra değişti" diye işaretler. Dönüş: işaretlenen var mı."""
    birim_id = y.agac.kisi_birimi(personel)
    if not birim_id:
        return False
    return bool(GunlukOnay.objects.filter(birim_id=birim_id, tarih__range=_gunler(bas, bit))
                .update(degisti=timezone.now()))


def _simdi():
    return timezone.localtime()


def ilk_giris_tarihi():
    """Bölüm hesabının kayıt başlatabileceği ilk gün: saat 09:00'dan önce bugün, sonra yarın."""
    simdi = _simdi()
    return simdi.date() if simdi.time() < GIRIS_SON_SAAT else simdi.date() + datetime.timedelta(days=1)


def _gunler(bas, bit):
    return timezone.localtime(bas).date(), timezone.localtime(bit - datetime.timedelta(microseconds=1)).date()


def kesinlesen_gunler(birim_id, bas, bit):
    if not birim_id:
        return []
    return list(GunlukOnay.objects.filter(birim_id=birim_id, tarih__range=_gunler(bas, bit))
                .order_by("tarih").values_list("tarih", flat=True))


def kilit_nedeni(y, personel, bas, bit):
    return _kilit(y, y.agac.kisi_birimi(personel), bas, bit)


def _kilit(y, birim_id, bas, bit):
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
    kesin = kesinlesen_gunler(birim_id, bas, bit)
    if kesin:
        gunler = ", ".join(f"{g:%d.%m.%Y}" for g in kesin[:5]) + (" …" if len(kesin) > 5 else "")
        return (f"{gunler} yoklaması kesinleşti; bu günlere değen kayıtları yalnız idari işler yetkilisi "
                "değiştirebilir.")
    return None


def kayit_kilitli_mi(y, kayit):
    return kilit_nedeni(y, kayit.personel, kayit.baslangic, kayit.bitis) is not None


def gun_kilidi(y, birim_id, tarih):
    """Birim hesabı bu güne kayıt giremiyorsa nedeni (ekranlarda düğmeleri kapatmak için)."""
    bas, bit = gun_araligi(tarih)
    return _kilit(y, birim_id, bas, bit)


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
    if not y.giris or not y.kapsar(personel):
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
    sonrasi = _onaylari_isaretle(y, personel, bas, bit)
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
    sonrasi = _onaylari_isaretle(y, k.personel, min(eski_bas, bas), max(eski_bit, bit))
    YoklamaGecmisi.objects.create(personel=k.personel, kayit_id=k.pk, islem=YoklamaGecmisi.DUZENLE,
                                  ozet=_ozet_metni(k)[:400], kullanici=user, onay_sonrasi=sonrasi)
    return k


@transaction.atomic
def sil(user, y, kayit_id):
    k = YoklamaKaydi.objects.select_related("personel", "tur").filter(pk=kayit_id).first()
    if k is None:
        return None
    if not y.giris or not y.kapsar(k.personel):
        raise YoklamaHatasi("Bu kaydı silme yetkiniz yok.")
    _kilit_denetle(y, k.personel, k.baslangic, k.bitis)
    ozet_ = _ozet_metni(k)
    personel, bas, bit = k.personel, k.baslangic, k.bitis
    k.delete()
    sonrasi = _onaylari_isaretle(y, personel, bas, bit)
    YoklamaGecmisi.objects.create(personel=personel, kayit_id=kayit_id, islem=YoklamaGecmisi.SIL, ozet=ozet_[:400],
                                  kullanici=user, onay_sonrasi=sonrasi)
    return personel


# ---------------------------------------------------------------- günlük kesinleştirme

def onay_yetkisi(y, birim):
    return bool(birim and birim.pk) and y.giris and y.kapsar_birim(birim.pk)


@transaction.atomic
def onayla(user, y, birim, tarih):
    if not onay_yetkisi(y, birim):
        raise YoklamaHatasi("Bu birimin yoklamasını kesinleştirme yetkiniz yok.")
    onay, yeni = GunlukOnay.objects.get_or_create(birim=birim, tarih=tarih, defaults={"onaylayan": user})
    if not yeni:  # yeniden kesinleştirildi: "değişti" işareti kalkar
        GunlukOnay.objects.filter(pk=onay.pk).update(onaylayan=user, zaman=timezone.now(), degisti=None)
    return onay


def birim_ozetleri(y, tarih, kok=None):
    """Kapsamdaki (ya da kok biriminin altındaki) birimlerin o günkü durumu, teşkilat sırasıyla:
    [{birim, derinlik, toplam, mevcut, gun_boyu, kismi, onay, alt_toplam, cocuklu}] — yalnız personeli olan dallar."""
    agac = y.agac
    kisiler = list(personeller(y, kok))
    by = defaultdict(list)
    for d in gun_durumu(tarih, kisiler):
        by[agac.kisi_birimi(d.personel)].append(d)
    alt_toplam = defaultdict(int)
    for bid, ds in by.items():
        for b in agac.zincir(bid):
            alt_toplam[b.pk] += len(ds)
    if kok is not None and kok.pk:
        kokler = [kok.pk]
    elif y.kapsam_birim is not None:
        kokler = [y.kapsam_birim.pk]
    else:
        kokler = None
    sira = [(b, d) for b, d in agac.sirali(kokler) if alt_toplam.get(b.pk)]
    if y.tum_okul and kok is None and by.get(0):
        sira.append((BIRIMSIZ, 0))
        alt_toplam[0] = len(by[0])
    onaylar = {o.birim_id: o for o in GunlukOnay.objects.filter(tarih=tarih, birim_id__in=[b.pk for b, _ in sira])
               .select_related("onaylayan")}
    out = []
    for b, d in sira:
        ds = by.get(b.pk, [])
        out.append({"birim": b, "derinlik": d, "toplam": len(ds), "mevcut": sum(x.mevcut for x in ds),
                    "gun_boyu": sum(x.gun_boyu for x in ds), "kismi": sum(x.kismi for x in ds),
                    "onay": onaylar.get(b.pk), "alt_toplam": alt_toplam.get(b.pk, 0),
                    "cocuklu": any(alt_toplam.get(c.pk) for c in agac.cocuklar.get(b.pk, []))})
    return out


def bolumle(ozetler):
    """Genel görünüm için gruplar: çocuklu her birim bir grup başlığı; içinde kendisi (personeli varsa) ve
    çocuksuz alt birimleri kutucuk olur. [{"baslik": birim, "kutular": [özet]}]"""
    gruplar, by = [], {o["birim"].pk: o for o in ozetler}
    for o in ozetler:
        b = o["birim"]
        if o["cocuklu"]:
            g = {"baslik": b, "kutular": [o] if o["toplam"] else []}
            gruplar.append(g)
            for c in ozetler:
                if c["birim"].ust_id == b.pk and not c["cocuklu"]:
                    g["kutular"].append(c)
        elif b.ust_id not in by or not by[b.ust_id]["cocuklu"]:
            gruplar.append({"baslik": None, "kutular": [o]})
    # başlıksız tek kutuları sonda bir grupta topla
    tekler = [k for g in gruplar if g["baslik"] is None for k in g["kutular"]]
    gruplar = [g for g in gruplar if g["baslik"] is not None and g["kutular"]]
    if tekler:
        gruplar.append({"baslik": None, "kutular": tekler})
    return gruplar


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    from django.urls import reverse

    y = yetki(request)
    if not y.giris:
        return []
    bugun = timezone.localdate()
    eksik = [o for o in birim_ozetleri(y, bugun) if o["toplam"] and o["birim"].pk and not o["onay"]]
    if not eksik:
        return []
    if not y.tum_okul:
        kendi = next((o for o in eksik if o["birim"] == y.kapsam_birim), None)
        if kendi and len(eksik) == 1:
            return [{"renk": "eksik", "ikon": "person-check", "sayi": None,
                     "ad": "Bugünün personel yoklaması kesinleştirilmedi",
                     "aciklama": f"{y.kapsam_birim.ad} · {bugun:%d.%m.%Y}", "url": reverse("yoklama:ana")}]
        return [{"renk": "eksik", "ikon": "person-check", "sayi": len(eksik),
                 "ad": "Yoklaması kesinleşmeyen birim", "aciklama": f"{y.kapsam_birim.ad} · {bugun:%d.%m.%Y}",
                 "url": reverse("yoklama:ana")}]
    if not y.yonetim:
        return []
    return [{"renk": "bekliyor", "ikon": "person-check", "sayi": len(eksik), "ad": "Yoklamayı kesinleştirmeyen birim",
             "aciklama": f"Bugün · {bugun:%d.%m.%Y}", "url": reverse("yoklama:ana")}]


def izin_turleri(sadece_aktif=True):
    qs = IzinTuru.objects.all()
    return qs.filter(aktif=True) if sadece_aktif else qs
