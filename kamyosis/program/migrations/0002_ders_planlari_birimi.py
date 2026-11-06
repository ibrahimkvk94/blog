"""Ders Planları birimini program modülüne bağlar."""

from django.db import migrations


def bagla(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug="ders-planlari").update(modul_url="program:ana", durum="kullanimda")


def coz(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug="ders-planlari").update(modul_url="", durum="sirada")


class Migration(migrations.Migration):
    dependencies = [("program", "0001_initial"), ("core", "0002_baslangic_agaci")]
    operations = [migrations.RunPython(bagla, coz)]
