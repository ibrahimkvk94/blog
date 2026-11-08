"""Personel kartına iki seçim alanı: Öğrenim durumu ve Kadro durumu (istatistikler bunları sayar)."""

from django.db import migrations

ALANLAR = [
    ("Öğrenim durumu", "Öğrenim", "Lise, Ön lisans, Lisans, Yüksek lisans, Doktora", 10),
    ("Kadro durumu", "Görev", "Muvazzaf, Kadrolu, Sözleşmeli, Atamalı, Görevlendirme", 5),
]


def ekle(apps, schema_editor):
    KartAlani = apps.get_model("personel", "KartAlani")
    for ad, grup, secenekler, sira in ALANLAR:
        KartAlani.objects.get_or_create(ad=ad, defaults={"grup": grup, "tur": "secim", "secenekler": secenekler,
                                                         "sira": sira, "aktif": True, "onemli": False})


class Migration(migrations.Migration):
    dependencies = [("personel", "0016_gelistirici")]
    operations = [migrations.RunPython(ekle, migrations.RunPython.noop)]
