"""Ölçme Değerlendirme › "Sınav İcrası" birimi kullanıma girer: sayfası sekmeli, ilk sekme Sınav Takvimi (herkese
açık; plan yükleme ve yayın Düzenleme yetkisi ister). Sınav Planları'nda Düzenleme ve üstü yetkisi olanlar başlangıçta
buraya da kopyalanır."""

from django.db import migrations


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Yetki = apps.get_model("core", "Yetki")
    olcme = Birim.objects.filter(slug="olcme-degerlendirme").first()
    b, _ = Birim.objects.get_or_create(
        slug="sinav-icrasi", defaults={"ad": "Sınav İcrası", "ust": olcme, "tur": "gorev", "sira": 1})
    b.durum, b.modul_url = "kullanimda", "sinavtakvimi:liste"
    b.ikon = b.ikon or "calendar2-week"
    b.aciklama = "Sınav takvimi (yayınlanan ara sınav ve final planları; herkes görür) ve sınavların yürütülmesi."
    b.save()
    sinav = Birim.objects.filter(slug="sinav-planlari").first()
    if sinav is not None:
        for y in Yetki.objects.filter(birim=sinav, seviye__gte=2):
            Yetki.objects.get_or_create(kullanici_id=y.kullanici_id, birim=b,
                                        defaults={"seviye": y.seviye, "kapsam": y.kapsam})


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="sinav-icrasi").update(durum="planlandi", modul_url="")


class Migration(migrations.Migration):
    dependencies = [
        ("sinavtakvimi", "0001_initial"),
        ("core", "0006_kisayol"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
