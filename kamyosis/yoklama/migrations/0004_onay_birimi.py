"""Günlük kesinleştirme bölüm yerine teşkilat birimine bağlanır (şube müdürlüğü, kısım … da kesinleştirir)."""

import django.db.models.deletion
from django.db import migrations, models


def doldur(apps, schema_editor):
    GunlukOnay = apps.get_model("yoklama", "GunlukOnay")
    T = apps.get_model("personel", "TeskilatBirimi")
    birimler = dict(T.objects.exclude(bolum=None).values_list("bolum_id", "pk"))
    for o in GunlukOnay.objects.all():
        pk = birimler.get(o.bolum_id)
        if pk is None:
            o.delete()
        else:
            GunlukOnay.objects.filter(pk=o.pk).update(birim_id=pk)


class Migration(migrations.Migration):

    dependencies = [
        ("yoklama", "0003_personel_grubu"),
        ("personel", "0012_bolum_birimleri"),
    ]

    operations = [
        migrations.AddField(
            model_name="gunlukonay", name="birim",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name="yoklama_onaylari", to="personel.teskilatbirimi"),
        ),
        migrations.RunPython(doldur, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name="gunlukonay", name="yoklama_onay_tekil"),
        migrations.RemoveField(model_name="gunlukonay", name="bolum"),
        migrations.AlterField(
            model_name="gunlukonay", name="birim",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yoklama_onaylari",
                                    to="personel.teskilatbirimi"),
        ),
        migrations.AddConstraint(
            model_name="gunlukonay",
            constraint=models.UniqueConstraint(fields=("birim", "tarih"), name="yoklama_onay_birim_tekil"),
        ),
    ]
