"""Devlet memurları sınav görevi almaz (Mehmet, 09.11.2026): rütbesiz ve unvanı memur unvanı olanlarda
"Sınav görevi alabilir" kapatılır. Kartlardan tek tek yeniden açılabilir."""

from django.db import migrations

MEMUR_UNVANLARI = {"De.Me.", "Söz.De.Me.", "VHKİ"}


def uygula(apps, schema_editor):
    Personel = apps.get_model("personel", "Personel")
    Personel.objects.filter(rutbe__isnull=True, unvan__metin__in=MEMUR_UNVANLARI, sinav_gorevi_alabilir=True).update(
        sinav_gorevi_alabilir=False)


class Migration(migrations.Migration):
    dependencies = [("personel", "0017_ogrenim_kadro_alanlari")]
    operations = [migrations.RunPython(uygula, migrations.RunPython.noop)]
