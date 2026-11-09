"""İdari İşler altında "Vekâlet" birimi. Vekâletler sekmesi bütün hesaplara görüntüleme yetkisiyle açılır (kullanıcı
ve yetkiler tablosundan kapatılabilir); vekâlet girişi düzenleme yetkisi isteyen ayrı sekmededir (İdari İşler
yetkilileri İdari İşler'deki yetkileriyle girer)."""

from django.conf import settings
from django.db import migrations


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Yetki = apps.get_model("core", "Yetki")
    Kullanici = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    ust = Birim.objects.filter(slug="idari-isler").first()
    birim, yeni = Birim.objects.get_or_create(slug="vekalet", defaults={
        "ad": "Vekâlet", "ust": ust, "tur": "gorev", "ikon": "arrow-left-right", "sira": 43,
        "durum": "kullanimda", "modul_url": "vekalet:liste",
        "aciklama": "Raporlu, izinli ya da görevli personelin görevini kime, hangi tarihe kadar bıraktığı."})
    if yeni:
        Yetki.objects.bulk_create([Yetki(kullanici_id=pk, birim=birim, seviye=1, kapsam="tum")
                                   for pk in Kullanici.objects.filter(is_active=True, is_superuser=False)
                                   .values_list("pk", flat=True)])


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="vekalet").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("vekalet", "0001_initial"),
        ("core", "0005_ders_takibi_devir_organizasyon"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [migrations.RunPython(uygula, geri)]
