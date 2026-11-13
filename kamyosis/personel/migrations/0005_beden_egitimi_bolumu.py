"""Beden Eğitimi ve Spor bölümü: TBE (Temel Beden Eğitimi) ve SBE (Savaş Beden Eğitimi) dersleri."""

from django.db import migrations


def ekle(apps, schema_editor):
    Bolum = apps.get_model("personel", "Bolum")
    b, _ = Bolum.objects.get_or_create(ad="Beden Eğitimi ve Spor")
    if not b.kod and not Bolum.objects.filter(kod="BES").exists():
        b.kod = "BES"
    b.ders_onekleri = "TBE,SBE"
    b.save()


def geri(apps, schema_editor):
    apps.get_model("personel", "Bolum").objects.filter(ad="Beden Eğitimi ve Spor", personeller__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("personel", "0004_bolum_ders_onekleri")]
    operations = [migrations.RunPython(ekle, geri)]
