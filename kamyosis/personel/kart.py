"""Personel kartı yardımcıları: ek bilgi alanları, teşkilat ağacı, ders / sınav kullanımı."""

import datetime
from collections import defaultdict

from django.db.models import Count, Q

from .models import Bolum, KartAlani, KartDegeri, Personel, TeskilatBirimi


def kart_bilgileri(p, sadece_dolu=False):
    """[(grup, [(alan, deger, gosterim)])] — kullanımdaki alanlar, grup sırasıyla."""
    degerler = {d.alan_id: d.deger for d in p.kart_degerleri.all()} if p.pk else {}
    gruplar = defaultdict(list)
    for a in KartAlani.objects.filter(aktif=True):
        d = degerler.get(a.pk, "")
        if sadece_dolu and not d:
            continue
        gruplar[a.grup].append((a, d, gosterim(a, d)))
    return list(gruplar.items())


def gosterim(alan, deger):
    if not deger:
        return ""
    if alan.tur == KartAlani.TARIH:
        try:
            return datetime.date.fromisoformat(deger).strftime("%d.%m.%Y")
        except ValueError:
            return deger
    return deger


def kart_kaydet(p, post):
    """POST'taki alan-<id> değerlerini yazar. Dönüş: değişen alan sayısı."""
    eski = {d.alan_id: d for d in p.kart_degerleri.all()}
    degisen = 0
    for a in KartAlani.objects.filter(aktif=True):
        anahtar = f"alan-{a.pk}"
        if anahtar not in post:
            continue
        yeni = post.get(anahtar, "").strip()[:2000]
        if a.tur == KartAlani.SECIM and yeni and yeni not in a.secenek_listesi:
            continue
        if a.tur == KartAlani.TARIH and yeni:
            try:
                datetime.date.fromisoformat(yeni)
            except ValueError:
                continue
        d = eski.get(a.pk)
        if d is None and not yeni:
            continue
        if d is not None and d.deger == yeni:
            continue
        if not yeni:
            d.delete()
        elif d is None:
            KartDegeri.objects.create(personel=p, alan=a, deger=yeni)
        else:
            d.deger = yeni
            d.save(update_fields=["deger", "guncelleme"])
        degisen += 1
    return degisen


# ---------------------------------------------------------------- teşkilat

def agac():
    """Kökler ve her düğümün çocukları (sıralı), personel sayıları ve sorumluları ile."""
    birimler = list(TeskilatBirimi.objects.filter(aktif=True).select_related("bolum__baskan__rutbe",
                                                                            "bolum__baskan__sinif",
                                                                            "bolum__baskan__unvan"))
    sayilar = dict(Personel.objects.filter(aktif=True, teskilat_birimi__isnull=False)
                   .values_list("teskilat_birimi").annotate(n=Count("pk")))
    bolum_sayilari = dict(Personel.objects.filter(aktif=True, teskilat_birimi__isnull=True, bolum__isnull=False)
                          .values_list("bolum").annotate(n=Count("pk")))
    sorumlular = {}
    for p in (Personel.objects.filter(aktif=True, teskilat_birimi__isnull=False).exclude(gorev_unvani="")
              .select_related("rutbe", "sinif", "unvan").order_by("-idari_kadro", "pk")):
        sorumlular.setdefault(p.teskilat_birimi_id, p)
    cocuklar = defaultdict(list)
    for b in birimler:
        b.sayi = sayilar.get(b.pk, 0) + (bolum_sayilari.get(b.bolum_id, 0) if b.bolum_id else 0)
        b.sorumlu = b.bolum.baskan if b.bolum_id and b.bolum.baskan_id else sorumlular.get(b.pk)
        cocuklar[b.ust_id].append(b)
    for b in birimler:
        b.cocuklar = cocuklar.get(b.pk, [])
        b.yardimcilar = [c for c in b.cocuklar if c.tur == TeskilatBirimi.YARDIMCI]
        b.kollar = [c for c in b.cocuklar if c.tur != TeskilatBirimi.YARDIMCI]
    return cocuklar.get(None, [])


def birim_personeli(birim):
    q = Q(teskilat_birimi=birim)
    if birim.bolum_id:
        q |= Q(teskilat_birimi__isnull=True, bolum_id=birim.bolum_id)
    return (Personel.objects.filter(q, aktif=True).select_related("bolum", "rutbe", "sinif", "unvan")
            .order_by("-idari_kadro", "ad_soyad"))


def teskilattaki_yeri(p):
    """Personelin teşkilattaki birim zinciri (kökten): [TeskilatBirimi]."""
    b = p.teskilat_birimi
    if b is None and p.bolum_id:
        b = TeskilatBirimi.objects.filter(bolum_id=p.bolum_id).first()
    zincir = []
    while b is not None and len(zincir) < 10:
        zincir.append(b)
        b = b.ust
    return list(reversed(zincir))


def baskan_ata(p, baskan_mi):
    """Personeli bölümünün başkanı yapar / başkanlıktan alır."""
    if p.bolum_id is None:
        return
    if baskan_mi:
        Bolum.objects.filter(pk=p.bolum_id).update(baskan=p)
    else:
        Bolum.objects.filter(pk=p.bolum_id, baskan=p).update(baskan=None)
