"""aSc öğretmenlerini personelle eşleştirme yardımcıları."""

from difflib import SequenceMatcher

from django.db import transaction

from personel.models import Personel

from .asc import ad_anahtari
from .models import ProgramOgretmeni

ONERI_ESIGI = 0.75


def oneriler(ogretmenler, personeller=None):
    """Her bekleyen öğretmen için en benzer personel: {ogretmen_pk: (personel, benzerlik)}."""
    if personeller is None:
        bagli = ProgramOgretmeni.objects.exclude(personel=None).values_list("personel_id", flat=True)
        personeller = list(Personel.objects.filter(derse_girebilir=True).exclude(pk__in=bagli))
    anahtarlar = [(p, ad_anahtari(p.ad_soyad)) for p in personeller]
    sonuc = {}
    for o in ogretmenler:
        hedef = ad_anahtari(o.ad)
        en_iyi = max(
            ((p, SequenceMatcher(None, hedef, a).ratio()) for p, a in anahtarlar),
            key=lambda x: x[1], default=(None, 0),
        )
        if en_iyi[1] >= ONERI_ESIGI:
            sonuc[o.pk] = en_iyi
    return sonuc


def eslestir(ogretmen, personel):
    ogretmen.personel, ogretmen.durum = personel, ProgramOgretmeni.ELLE
    ogretmen.save(update_fields=["personel", "durum", "guncelleme"])


def yeni_personel_olarak_ekle(ogretmen):
    p = Personel.objects.create(ad_soyad=ogretmen.ad, bolum=ogretmen.tahmini_bolum)
    ogretmen.personel, ogretmen.durum = p, ProgramOgretmeni.YENI
    ogretmen.save(update_fields=["personel", "durum", "guncelleme"])
    return p


def yok_say(ogretmen):
    ogretmen.personel, ogretmen.durum = None, ProgramOgretmeni.YOK_SAY
    ogretmen.save(update_fields=["personel", "durum", "guncelleme"])


def geri_al(ogretmen):
    """Eşleşmeyi kaldırır. Bu öğretmen için açılmış personel kaydı silinmez."""
    ogretmen.personel, ogretmen.durum = None, ProgramOgretmeni.BEKLIYOR
    ogretmen.save(update_fields=["personel", "durum", "guncelleme"])


@transaction.atomic
def onerisizleri_toplu_ekle(ogretmenler):
    """Benzer personel önerisi olmayan bekleyen öğretmenlerin hepsini yeni personel olarak ekler."""
    bekleyen = [o for o in ogretmenler if o.durum == ProgramOgretmeni.BEKLIYOR]
    oneri = oneriler(bekleyen)
    eklenen = 0
    for o in bekleyen:
        if o.pk not in oneri:
            yeni_personel_olarak_ekle(o)
            eklenen += 1
    return eklenen, len(oneri)
