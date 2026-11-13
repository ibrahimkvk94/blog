"""Bölüm başkanları sınav görevi almaz ve sınav mazereti listesine girmez (Mehmet, 09.11.2026): bölüm başkanı olarak
kayıtlı personelde "Sınav görevi alabilir" kapatılır. Mazeret listesi ayrıca başkanları her zaman dışarıda bırakır."""

from django.db import migrations


def uygula(apps, schema_editor):
    Bolum = apps.get_model("personel", "Bolum")
    Personel = apps.get_model("personel", "Personel")
    baskanlar = Bolum.objects.filter(baskan__isnull=False).values_list("baskan_id", flat=True)
    Personel.objects.filter(pk__in=list(baskanlar), sinav_gorevi_alabilir=True).update(sinav_gorevi_alabilir=False)


class Migration(migrations.Migration):
    dependencies = [("personel", "0018_memurlar_sinav_gorevi_almaz")]
    operations = [migrations.RunPython(uygula, migrations.RunPython.noop)]
