"""Bildirim gönderme ve modüllerden gelen olaylar.

Olay fonksiyonları ana işlemi asla bozmaz: bildirim üretilirken bir hata olursa kaydedilir ve işlem sürer.
"""

import logging
from datetime import datetime, time, timedelta
from functools import wraps
from types import SimpleNamespace

from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from .models import Bildirim, BildirimTercihi, ZamanliIs
from .turler import DUZENLEME, GORUNTULEME, TURLER, YONETIM, alabilenler, herkes, yetkililer

log = logging.getLogger(__name__)

SAKLAMA_GUNU = 30
OZET_SAATLERI = (("sabah", time(9, 30)), ("ogle", time(14, 0)))


def gonder(tur_kod, alicilar, baslik, metin="", url="", haric=None):
    """Alıcılara bildirim yazar; türü kapatan ve işlemi yapan hariç. Yazılan sayıyı döner."""
    idler = set(alicilar)
    if haric is not None:
        idler.discard(haric.pk)
    if not idler:
        return 0
    kapali = set(BildirimTercihi.objects.filter(tur=tur_kod, mod=BildirimTercihi.KAPALI, kullanici_id__in=idler)
                 .values_list("kullanici_id", flat=True))
    simdi = timezone.now()
    yeni = [Bildirim(kullanici_id=k, tur=tur_kod, baslik=baslik[:150], metin=metin[:400], url=url[:300],
                     olusturma=simdi) for k in sorted(idler - kapali)]
    Bildirim.objects.bulk_create(yeni)
    return len(yeni)


def _guvenli(f):
    @wraps(f)
    def sarmal(*args, **kwargs):
        try:
            with transaction.atomic():
                return f(*args, **kwargs)
        except Exception:  # bildirim yüzünden asıl işlem bozulmasın
            log.exception("Bildirim üretilemedi: %s", f.__name__)
            return 0

    return sarmal


def _sahte_istek(user_id):
    from django.contrib.auth import get_user_model

    return SimpleNamespace(user=get_user_model().objects.get(pk=user_id))


# ---------------------------------------------------------------- olaylar

@_guvenli
def vekalet(v, user, islem="kaydedildi"):
    """islem: kaydedildi (yeni), degisti, sonlandirildi, geri_alindi."""
    from vekalet import servis as vs

    alicilar = set()
    for uid, (seviye, kapsam) in yetkililer("vekalet", DUZENLEME).items():
        if kapsam != "bolum":
            alicilar.add(uid)
            continue
        if uid == getattr(user, "pk", None):
            continue
        y = vs.yetki(_sahte_istek(uid))
        if y.duzenle and (y.veren_idler is None or v.veren_id in y.veren_idler):
            alicilar.add(uid)
    baslik = {"kaydedildi": "Yeni vekâlet", "degisti": "Vekâlet değişti", "sonlandirildi": "Vekâlet sonlandırıldı",
              "geri_alindi": "Vekâlet sonlandırması geri alındı"}.get(islem, "Vekâlet")
    metin = f"{v.gorev}: {v.veren.ad_soyad} → vekili {v.vekil.ad_soyad} · {v.aralik_metni}"
    return gonder("vekalet", alicilar, baslik, metin, reverse("vekalet:liste"), haric=user)


@_guvenli
def mazeret_teslimi(tur, donem, bolum, user):
    from mazeret import servis as ms

    alicilar = yetkililer(tur.birim, YONETIM, tum_okul=True)
    durumlar = ms.bolum_durumlari(tur, donem, ms.MazeretYetkisi(goruntule=True, tur_kod=tur.kod))
    tamam = sum(1 for d in durumlar if d["teslim"] is not None)
    metin = f"{bolum.ad} · {donem.ad} · {tamam}/{len(durumlar)} bölüm tamam"
    url = reverse(tur.url("tablo"), args=[donem.pk])
    return gonder("mazeret_teslimi", alicilar, f"{tur.baslik} kesinleşti", metin, url, haric=user)


@_guvenli
def ders_programi(s, user):
    metin = f"“{s.ad}” · {s.baslangic:%d.%m.%Y} tarihinden itibaren geçerli"
    return gonder("ders_programi", yetkililer("ders-planlari", GORUNTULEME), "Ders programı yayınlandı", metin,
                  reverse("program:ana"), haric=user)


@_guvenli
def sinav_programi(d, user):
    metin = f"“{d.name}” · takvim, sınıflar ve görevlendirmeler görülebilir"
    return gonder("sinav_programi", yetkililer("sinav-planlari", GORUNTULEME), "Sınav programı yayınlandı", metin,
                  reverse("dersprogrami_kopru:sinav_programi_donem", args=[d.pk]), haric=user)


@_guvenli
def sinav_takvimi(t, user):
    from sinavtakvimi import servis as st

    o = st.ozet(t)
    aralik = ""
    if o["ilk"]:
        aralik = st.tarih_metni(o["ilk"], gun=False) if o["ilk"] == o["son"] else (
            f"{o['ilk'].day} {st.AYLAR[o['ilk'].month - 1]} – {st.tarih_metni(o['son'], gun=False)}")
    metin = f"“{t.ad}” · {aralik} · {o['sinav']} sınav" if aralik else f"“{t.ad}”"
    return gonder("sinav_takvimi", herkes(), "Sınav planı yayınlandı", metin,
                  reverse("sinavtakvimi:takvim", args=[t.pk]), haric=user)


@_guvenli
def nobet(d, user):
    return gonder("nobet", yetkililer("nobet-gruplari", GORUNTULEME), "Nöbet grupları kesinleşti",
                  f"{d} nöbet grupları yayında", reverse("nobet:donem", args=[d.yil, d.ay]), haric=user)


# ---------------------------------------------------------------- yoklama özeti ve temizlik

def _bir_kez(anahtar):
    """İş bugün yapılmadıysa yapıldı işaretler ve True döner (eşzamanlı iki istekte yalnız biri)."""
    try:
        with transaction.atomic():
            ZamanliIs.objects.create(anahtar=anahtar)
        return True
    except IntegrityError:
        return False


_yapilanlar = set()  # süreç içi önbellek: her yoklamada veritabanına sormamak için


def zamanli_isler(simdi=None):
    simdi = timezone.localtime(simdi or timezone.now())
    bugun = simdi.date()
    anahtarlar = [f"temizlik:{bugun}"]
    if bugun.weekday() < 5:
        gecen = [ad for ad, saat in OZET_SAATLERI if simdi.time() >= saat]
        if gecen:  # sunucu geç açıldıysa yalnız son özet
            anahtarlar.append(f"yoklama:{bugun}:{gecen[-1]}")
    for a in anahtarlar:
        if a in _yapilanlar:
            continue
        _yapilanlar.add(a)
        if not _bir_kez(a):
            continue
        if a.startswith("temizlik"):
            _temizle(simdi)
        else:
            yoklama_ozeti(bugun, a.rsplit(":", 1)[1])


def _temizle(simdi):
    Bildirim.objects.filter(olusturma__lt=simdi - timedelta(days=SAKLAMA_GUNU)).delete()
    ZamanliIs.objects.filter(zaman__lt=simdi - timedelta(days=60)).delete()


def yoklama_ozeti_metni(bugun, donem):
    from yoklama import servis as ys
    from yoklama.birim import Agac
    from yoklama.models import GunlukOnay, YoklamaKaydi

    y = ys.YoklamaYetkisi(goruntule=True, giris=True, yonetim=True, agac=Agac())
    ozetler = ys.birim_ozetleri(y, bugun)
    birimler = [o for o in ozetler if o["toplam"] and o["birim"].pk]
    kesin = [o for o in birimler if o["onay"]]
    eksik = [o["birim"].ad for o in birimler if not o["onay"]]
    gayri = sum(o["gun_boyu"] for o in ozetler)
    kismi = sum(o["kismi"] for o in ozetler)
    parcalar = [f"{len(kesin)}/{len(birimler)} birim kesinleştirdi", f"{gayri} kişi gün boyu gayri mevcut"]
    if kismi:
        parcalar.append(f"{kismi} kişi saatlik izinli")
    if donem == "ogle":
        sinir = timezone.make_aware(datetime.combine(bugun, OZET_SAATLERI[0][1]))
        sonradan = YoklamaKaydi.objects.filter(olusturma__gte=sinir, baslangic__date__lte=bugun,
                                               bitis__date__gte=bugun).count()
        degisen = GunlukOnay.objects.filter(tarih=bugun, degisti__isnull=False).count()
        if sonradan:
            parcalar.append(f"09.30'dan sonra {sonradan} kayıt girildi")
        if degisen:
            parcalar.append(f"{degisen} birimde onaydan sonra değişiklik")
    if eksik:
        fazla = f" +{len(eksik) - 4}" if len(eksik) > 4 else ""
        parcalar.append("eksik: " + ", ".join(eksik[:4]) + fazla)
    baslik = "Yoklama özeti · " + ("sabah" if donem == "sabah" else "öğleden sonra")
    return baslik, " · ".join(parcalar)


@_guvenli
def yoklama_ozeti(bugun, donem):
    baslik, metin = yoklama_ozeti_metni(bugun, donem)
    return gonder("yoklama_ozeti", yetkililer("personel-yoklamasi", YONETIM, tum_okul=True), baslik, metin,
                  reverse("yoklama:ana"))


# ---------------------------------------------------------------- kullanıcı tarafı

def tercihler(user):
    return dict(BildirimTercihi.objects.filter(kullanici=user).values_list("tur", "mod"))


def ayar_satirlari(user):
    secimler = tercihler(user)
    return [{"tur": t, "mod": secimler.get(t.kod, BildirimTercihi.ACIK)}
            for t in TURLER.values() if user.pk in alabilenler(t)]


def tercih_yaz(user, tur_kod, mod):
    if tur_kod not in TURLER or mod not in dict(BildirimTercihi.MODLAR):
        raise ValueError(tur_kod)
    BildirimTercihi.objects.update_or_create(kullanici=user, tur=tur_kod, defaults={"mod": mod})


def okunmamis_sayisi(user):
    return Bildirim.objects.filter(kullanici=user, okundu__isnull=True).count()


def sozluk(b, sessizler=()):
    t = TURLER.get(b.tur)
    return {"id": b.pk, "tur": b.tur, "baslik": b.baslik, "metin": b.metin,
            "ikon": t.ikon if t else "bell", "renk": t.renk if t else "gri",
            "url": reverse("bildirim:ac", args=[b.pk]), "zaman": timezone.localtime(b.olusturma).strftime("%H:%M"),
            "sessiz": b.tur in sessizler, "tur_adi": t.ad if t else ""}
