"""Vekâlet kuralları: yetki, görev önerisi, yoklamadaki izinlerden tarih önerisi, çakışma ve uyarılar."""

import datetime
from dataclasses import dataclass

from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from core.yetki import DUZENLEME, GORUNTULEME, birim_bul, etkin_yetki
from personel.models import Bolum, Personel

from .models import Vekalet

BIRIM = "vekalet"
GUN = datetime.timedelta(days=1)

# yoklamadaki izin türü grubu → vekâlet nedeni
GRUP_NEDEN = {"saglik": Vekalet.RAPOR, "izin": Vekalet.IZIN, "aile": Vekalet.IZIN, "gorev": Vekalet.GOREV,
              "egitim": Vekalet.KURS}


@dataclass
class Yetkisi:
    goruntule: bool = False
    duzenle: bool = False


def yetki(request):
    try:
        seviye, _ = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye = 0
    return Yetkisi(goruntule=seviye >= GORUNTULEME, duzenle=seviye >= DUZENLEME)


def personel_listesi():
    return Personel.objects.filter(aktif=True).select_related("unvan", "rutbe", "sinif", "bolum").order_by("ad_soyad")


def gorev_onerileri():
    """{personel_id: görev adı}: bölüm başkanı → "<Bölüm> Bölüm Başkanı", yoksa kartındaki görev unvanı."""
    out = {p.pk: p.gorev_unvani for p in Personel.objects.filter(aktif=True).exclude(gorev_unvani="").only("gorev_unvani")}
    for b in Bolum.objects.filter(baskan__isnull=False, aktif=True):
        out[b.baskan_id] = f"{b.ad} Bölüm Başkanı"
    return out


def _gun_araligi(kayit):
    """Yoklama kaydının kapsadığı günler (bitiş gece yarısıysa önceki gün)."""
    bas, bit = timezone.localtime(kayit.baslangic), timezone.localtime(kayit.bitis)
    son = bit.date() - GUN if bit.time() == datetime.time(0) else bit.date()
    return bas.date(), max(son, bas.date())


def yaklasan_izinler(gun=90):
    """{personel_id: [{ad, bas, bit, neden}]}: bugünden itibaren yoklamadaki izin / rapor / görev kayıtları
    (formda vekâlet verenin tarihlerini tek tıkla doldurmak için)."""
    from yoklama.models import YoklamaKaydi

    simdi = timezone.now()
    out = {}
    qs = (YoklamaKaydi.objects.filter(bitis__gt=simdi, baslangic__lt=simdi + datetime.timedelta(days=gun),
                                      personel__aktif=True)
          .exclude(tur__mevcut_sayilir=True).select_related("tur").order_by("baslangic"))
    for k in qs:
        bas, bit = _gun_araligi(k)
        out.setdefault(k.personel_id, []).append({
            "ad": k.tur.ad, "bas": bas.isoformat(), "bit": bit.isoformat(),
            "neden": GRUP_NEDEN.get(k.tur.grup, Vekalet.DIGER),
            "metin": f"{bas:%d.%m}" + ("" if bas == bit else f"–{bit:%d.%m}")})
    return out


def _ortusen(qs, bas, bit):
    return qs.filter(sonlandirma__isnull=True, baslangic__lte=bit, bitis__gte=bas)


def kontrol(v):
    """(hatalar, uyarılar). Hata kaydı engeller; uyarı onaylanırsa kaydedilir."""
    hatalar, uyarilar = [], []
    if v.veren_id and v.veren_id == v.vekil_id:
        hatalar.append("Personel kendisine vekâlet veremez.")
    if hatalar or not (v.baslangic and v.bitis and v.veren_id and v.vekil_id):
        return hatalar, uyarilar
    diger = Vekalet.objects.exclude(pk=v.pk)
    for c in _ortusen(diger.filter(veren_id=v.veren_id), v.baslangic, v.bitis):
        if c.gorev.strip().casefold() == v.gorev.strip().casefold():
            hatalar.append(f"{c.veren.ad_soyad} bu tarihlerde “{c.gorev}” görevi için zaten vekâlet vermiş "
                           f"(vekil: {c.vekil.ad_soyad}, {c.aralik_metni}).")
        else:
            uyarilar.append(f"{c.veren.ad_soyad} aynı tarihlerde “{c.gorev}” görevi için de vekâlet vermiş "
                            f"(vekil: {c.vekil.ad_soyad}, {c.aralik_metni}).")
    for c in _ortusen(diger.filter(veren_id=v.vekil_id), v.baslangic, v.bitis):
        uyarilar.append(f"Vekil {c.veren.ad_soyad} bu tarihlerde kendisi de “{c.gorev}” görevi için vekâlet vermiş "
                        f"(vekili: {c.vekil.ad_soyad}, {c.aralik_metni}).")
    from yoklama.servis import kayitlar

    tz = timezone.get_current_timezone()
    bas = timezone.make_aware(datetime.datetime.combine(v.baslangic, datetime.time(0)), tz)
    bit = timezone.make_aware(datetime.datetime.combine(v.bitis + GUN, datetime.time(0)), tz)
    for k in kayitlar([v.vekil_id], bas, bit, yoklama=True):
        b, s = _gun_araligi(k)
        uyarilar.append(f"Vekil {k.personel.ad_soyad} personel yoklamasında {b:%d.%m}"
                        + ("" if b == s else f"–{s:%d.%m}") + f" tarihlerinde “{k.tur.ad}” görünüyor.")
    return hatalar, uyarilar


def gruplar(tumu=False, gecmis_gun=60):
    """Vekâletler sekmesi: (yürürlükte, başlayacak, geçmiş). Geçmiş son `gecmis_gun` gün (tumu=True: hepsi)."""
    bugun = timezone.localdate()
    qs = Vekalet.objects.select_related("veren__unvan", "veren__rutbe", "veren__sinif", "vekil__unvan",
                                        "vekil__rutbe", "vekil__sinif", "veren__bolum")
    acik = qs.filter(sonlandirma__isnull=True)
    yururlukte = list(acik.filter(baslangic__lte=bugun, bitis__gte=bugun).order_by("bitis", "veren__ad_soyad"))
    baslayacak = list(acik.filter(baslangic__gt=bugun).order_by("baslangic", "veren__ad_soyad"))
    gecmis = qs.filter(Q(sonlandirma__isnull=False) | Q(bitis__lt=bugun)).order_by("-bitis", "-pk")
    if not tumu:
        gecmis = gecmis.filter(bitis__gte=bugun - datetime.timedelta(days=gecmis_gun))
    return yururlukte, baslayacak, list(gecmis)


# ---------------------------------------------------------------- başka sayfalarda gösterim

def harita(bugun=None):
    """Bugün yürürlükte olan vekâletler: {personel_id: {"asil": [vekâlet verdiği], "vekil": [vekili olduğu]}}."""
    bugun = bugun or timezone.localdate()
    out = {}
    for v in (Vekalet.objects.filter(sonlandirma__isnull=True, baslangic__lte=bugun, bitis__gte=bugun)
              .select_related("veren", "vekil").order_by("bitis")):
        out.setdefault(v.veren_id, {"asil": [], "vekil": []})["asil"].append(v)
        out.setdefault(v.vekil_id, {"asil": [], "vekil": []})["vekil"].append(v)
    return out


# ---------------------------------------------------------------- vekâleti girilmemiş yöneticiler

def yoneticiler():
    """Vekâlet bırakması beklenen personel: bölüm başkanları ve birim yöneticisi unvanlılar (müdür, amir, başkan …)."""
    from personel.kart import gorev_derecesi

    baskanlar = set(Bolum.objects.filter(baskan__isnull=False, aktif=True).values_list("baskan_id", flat=True))
    kisiler = Personel.objects.filter(aktif=True).filter(Q(pk__in=baskanlar) | ~Q(gorev_unvani=""))
    return [p for p in kisiler if p.pk in baskanlar or gorev_derecesi(p) <= 2]


def eksik_vekaletler(gun=7, bugun=None):
    """Önümüzdeki `gun` gün içinde yoklamada tam gün (en az 20 saat) izinli / raporlu / görevli görünen ve o tarihler
    için vekâleti girilmemiş yöneticiler: [{personel, gorev, tur, bas, bit, neden}] (başlangıca göre)."""
    from yoklama.servis import kayitlar

    bugun = bugun or timezone.localdate()
    kisiler = {p.pk: p for p in yoneticiler()}
    if not kisiler:
        return []
    tz = timezone.get_current_timezone()
    bas = timezone.make_aware(datetime.datetime.combine(bugun, datetime.time(0)), tz)
    bit = bas + datetime.timedelta(days=gun + 1)
    gorevler = gorev_onerileri()
    vekaletler = list(Vekalet.objects.filter(veren_id__in=kisiler, sonlandirma__isnull=True, bitis__gte=bugun))
    out, gorulen = [], set()
    for k in kayitlar(list(kisiler), bas, bit, yoklama=True):
        if k.bitis - k.baslangic < datetime.timedelta(hours=20):
            continue
        b, s = _gun_araligi(k)
        b = max(b, bugun)
        if b > s or (k.personel_id, b) in gorulen:
            continue
        if any(v.veren_id == k.personel_id and v.baslangic <= s and v.bitis >= b for v in vekaletler):
            continue
        gorulen.add((k.personel_id, b))
        out.append({"personel": kisiler[k.personel_id], "gorev": gorevler.get(k.personel_id, ""), "tur": k.tur.ad,
                    "bas": b, "bit": s, "neden": GRUP_NEDEN.get(k.tur.grup, Vekalet.DIGER)})
    return sorted(out, key=lambda e: (e["bas"], e["personel"].ad_soyad))


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    """Vekâlet girişi yapanlara "vekâleti girilmemiş yönetici", görüntüleyenlere "yürürlükteki vekâletler"."""
    from django.urls import reverse

    y = yetki(request)
    gorevler = []
    if y.duzenle:
        eksik = eksik_vekaletler()
        if eksik:
            ilk = eksik[0]
            gorevler.append({
                "renk": "eksik", "ikon": "person-exclamation", "sayi": len(eksik), "ad": "Vekâleti girilmemiş yönetici",
                "aciklama": f"{ilk['personel'].ad_soyad} · {ilk['tur']} {ilk['bas']:%d.%m}"
                            + (f" ve {len(eksik) - 1} kişi daha" if len(eksik) > 1 else ""),
                "url": reverse("vekalet:islemler")})
    if y.goruntule:
        bugun = timezone.localdate()
        aktif = list(Vekalet.objects.filter(sonlandirma__isnull=True, baslangic__lte=bugun, bitis__gte=bugun)
                     .select_related("veren", "vekil").order_by("bitis"))
        if aktif:
            v = aktif[0]
            gorevler.append({
                "renk": "bekliyor", "ikon": "arrow-left-right", "sayi": len(aktif), "ad": "Yürürlükte vekâlet",
                "aciklama": f"{v.gorev}: {v.vekil.ad_soyad} (bitiş {v.bitis:%d.%m})"
                            + (f" · +{len(aktif) - 1} vekâlet" if len(aktif) > 1 else ""),
                "url": reverse("vekalet:liste")})
    return gorevler
