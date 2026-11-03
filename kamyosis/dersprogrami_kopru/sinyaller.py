"""Yetki, birim ya da kullanıcı değişince modül üyeliklerini; personel künyesi değişince öğretmen
"ünvan / rütbe" alanını güncel tutar."""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.signals import post_delete, post_save

from core.models import Birim, Yetki

log = logging.getLogger(__name__)


def _guvenli(is_):
    def calistir():
        try:
            is_()
        except Exception:  # eşitleme hatası asıl kaydı bozmasın; `ders_programi_yetki_esitle` ile düzeltilir
            log.exception("Ders Programı yetki eşitlemesi başarısız")

    transaction.on_commit(calistir)


def _yetki_degisti(sender, instance, **kwargs):
    from .yetki import esitle

    kullanici_id = instance.kullanici_id
    _guvenli(lambda: [esitle(u) for u in get_user_model().objects.filter(pk=kullanici_id)])


def _birim_degisti(sender, instance, **kwargs):
    from .yetki import hepsini_esitle

    _guvenli(hepsini_esitle)


def _kullanici_degisti(sender, instance, created, update_fields=None, **kwargs):
    if update_fields and not {"is_active", "is_superuser"} & set(update_fields):
        return  # ör. yalnızca last_login
    from .yetki import esitle

    _guvenli(lambda: esitle(instance))


def _kunye_personel(sender, instance, **kwargs):
    from .kunye import kunyeleri_esitle

    pk = instance.pk
    _guvenli(lambda: kunyeleri_esitle(personel_idler={pk}))


def _kunye_hepsi(sender, instance, **kwargs):
    """Rütbe/sınıf/unvan metni ya da aSc öğretmeni–personel eşleşmesi değişti."""
    from .kunye import kunyeleri_esitle

    _guvenli(kunyeleri_esitle)


def _kunye_ogretmen(sender, instance, **kwargs):
    """Modülde öğretmen eklendi ya da değişti (ör. aSc'den aktarım): o programın künyeleri."""
    from .kunye import kunyeleri_esitle

    okul_id = instance.school_id
    _guvenli(lambda: kunyeleri_esitle(okullar=type(instance.school).objects.filter(pk=okul_id)))


def bagla():
    from personel.models import Personel, Secenek
    from program.models import ProgramOgretmeni
    from timetable.models import Teacher

    post_save.connect(_kunye_personel, sender=Personel, dispatch_uid="dp_kunye_personel")
    post_save.connect(_kunye_hepsi, sender=Secenek, dispatch_uid="dp_kunye_secenek")
    post_save.connect(_kunye_hepsi, sender=ProgramOgretmeni, dispatch_uid="dp_kunye_eslesme")
    post_save.connect(_kunye_ogretmen, sender=Teacher, dispatch_uid="dp_kunye_ogretmen")
    post_save.connect(_yetki_degisti, sender=Yetki, dispatch_uid="dp_yetki_kaydet")
    post_delete.connect(_yetki_degisti, sender=Yetki, dispatch_uid="dp_yetki_sil")
    post_save.connect(_birim_degisti, sender=Birim, dispatch_uid="dp_birim_kaydet")
    post_delete.connect(_birim_degisti, sender=Birim, dispatch_uid="dp_birim_sil")
    post_save.connect(_kullanici_degisti, sender=get_user_model(), dispatch_uid="dp_kullanici_kaydet")
