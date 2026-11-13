"""Teşkilatta karşılığı olmayan her aktif bölüm için bir "bölüm başkanlığı" birimi açar (yoklama kapsamı birimden)."""

from django.db import migrations


def ileri(apps, schema_editor):
    Bolum = apps.get_model("personel", "Bolum")
    T = apps.get_model("personel", "TeskilatBirimi")
    ust = T.objects.filter(tur="baskanliklar").order_by("pk").first()
    for b in Bolum.objects.filter(aktif=True).order_by("ad"):
        if not T.objects.filter(bolum=b).exists():
            T.objects.create(ad=b.ad, tur="bolum", ust=ust, bolum=b,
                             sira=(T.objects.filter(ust=ust).count() + 1) * 10 if ust else 0)


class Migration(migrations.Migration):

    dependencies = [("personel", "0011_kart_alanlari_ve_ad")]

    operations = [migrations.RunPython(ileri, migrations.RunPython.noop)]
