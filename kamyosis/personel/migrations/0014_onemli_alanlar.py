"""Başlangıçta eksik sayılacak kart alanları (yöneticiler Kart alanları sayfasından değiştirir)."""

from django.db import migrations

ONEMLI = ["Cep telefonu", "Ev adresi", "Kan grubu", "Acil durum telefonu"]


def ileri(apps, schema_editor):
    apps.get_model("personel", "KartAlani").objects.filter(ad__in=ONEMLI).update(onemli=True)


class Migration(migrations.Migration):

    dependencies = [("personel", "0013_kart_alani_onemli")]

    operations = [migrations.RunPython(ileri, migrations.RunPython.noop)]
