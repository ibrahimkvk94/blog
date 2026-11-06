"""İdari İşler altında "Kimlik Kartı Okuma" birimi."""

from django.db import migrations


def kur(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    idari = Birim.objects.filter(slug="idari-isler").first()
    if idari is not None:
        Birim.objects.update_or_create(slug="kimlik-okuma", defaults={
            "ad": "Kimlik Kartı Okuma", "ust": idari, "tur": "gorev", "sira": 45, "ikon": "upc-scan",
            "durum": "kullanimda", "modul_url": "kimlik:liste",
            "aciklama": "T.C. kimlik kartının telefonla çekilen fotoğrafından bilgileri okur (bu sunucuda, fotoğraf "
                        "saklanmadan); liste Excel'e alınır, personel ya da öğrenci olarak işaretlenip personel "
                        "kartlarına veya öğrenci kaydına aktarılır.",
        })


def geri_al(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="kimlik-okuma").delete()


class Migration(migrations.Migration):

    dependencies = [("kimlik", "0001_initial"), ("core", "0003_bolum_menusu")]

    operations = [migrations.RunPython(kur, geri_al)]
