""""Öğrenci Kaydı" birimi kullanıma açılır (öğrenci kütüğü)."""

from django.db import migrations


def kur(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="ogrenci-kaydi").update(
        durum="kullanimda", modul_url="ogrenci:liste")


def geri_al(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="ogrenci-kaydi").update(durum="planlandi", modul_url="")


class Migration(migrations.Migration):

    dependencies = [("ogrenci", "0001_initial"), ("core", "0003_bolum_menusu")]

    operations = [migrations.RunPython(kur, geri_al)]
