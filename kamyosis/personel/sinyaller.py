"""Her bölümün teşkilat şemasında bir "bölüm başkanlığı" birimi olur (yoklama ve yetki kapsamı birim üzerinden)."""

from django.db.models.signals import post_save


def bolum_birimi_olustur(Bolum, TeskilatBirimi, bolum):
    if not bolum.aktif or TeskilatBirimi.objects.filter(bolum=bolum).exists():
        return None
    ust = TeskilatBirimi.objects.filter(tur="baskanliklar").order_by("pk").first()
    sira = (ust.altlar.count() + 1) * 10 if ust else 0
    return TeskilatBirimi.objects.create(ad=bolum.ad, tur="bolum", ust=ust, bolum=bolum, sira=sira)


def _bolum_kaydedildi(sender, instance, **kwargs):
    from .models import Bolum, TeskilatBirimi

    bolum_birimi_olustur(Bolum, TeskilatBirimi, instance)


def bagla():
    from .models import Bolum

    post_save.connect(_bolum_kaydedildi, sender=Bolum, dispatch_uid="personel_bolum_birimi")
