"""Garnizon terk türü geri eklendi (09.11.2026): bilgi amaçlı, personel mevcut sayılır."""

from django.db import migrations


def uygula(apps, schema_editor):
    IzinTuru = apps.get_model("yoklama", "IzinTuru")
    t = IzinTuru.objects.filter(ad="Garnizon terk").first() or IzinTuru(ad="Garnizon terk")
    t.kisa, t.renk, t.grup, t.sira, t.aktif, t.mevcut_sayilir = "GT", "#475569", "diger", 900, True, True
    t.aciklama = t.aciklama or "Bilgi amaçlı: personel kartında görünür, yoklamada mevcut sayılır."
    t.save()


class Migration(migrations.Migration):
    dependencies = [("yoklama", "0008_izin_turleri_listesi")]
    operations = [migrations.RunPython(uygula, migrations.RunPython.noop)]
