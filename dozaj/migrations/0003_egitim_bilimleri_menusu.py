"""Menüde yeni kök birim "Eğitim Bilimleri" ve altında "Öğretim Programları" (Dozajmatik'in program sayfaları, kendi
yetkisiyle). Dozajmatik'e doğrudan verilmiş yetkiler başlangıçta Öğretim Programları'na da kopyalanır.
Ayrıca menüde "Öğrenci İşleri Şube Müdürlüğü" adı "Öğrenci İşleri" olur."""

from django.db import migrations


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Yetki = apps.get_model("core", "Yetki")
    kok, _ = Birim.objects.get_or_create(
        slug="egitim-bilimleri",
        defaults={"ad": "Eğitim Bilimleri", "tur": "sube", "ikon": "book", "sira": 30, "durum": "planlandi",
                  "aciklama": "Öğretim programları ve eğitim-öğretim planlaması."})
    op, yeni = Birim.objects.get_or_create(
        slug="ogretim-programlari",
        defaults={"ad": "Öğretim Programları", "ust": kok, "tur": "gorev", "ikon": "journal-text", "sira": 10,
                  "durum": "kullanimda", "modul_url": "dozaj:op_programlar",
                  "aciklama": "Programların yarıyıllara göre dersleri ve kısım sayıları."})
    if yeni:
        for y in Yetki.objects.filter(birim__slug="dozajmatik"):
            Yetki.objects.get_or_create(kullanici_id=y.kullanici_id, birim=op,
                                        defaults={"seviye": y.seviye, "kapsam": y.kapsam})
    Birim.objects.filter(slug="ogrenci-isleri-sube", ad="Öğrenci İşleri Şube Müdürlüğü").update(ad="Öğrenci İşleri")


def geri(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug="ogretim-programlari").delete()
    Birim.objects.filter(slug="egitim-bilimleri").delete()
    Birim.objects.filter(slug="ogrenci-isleri-sube", ad="Öğrenci İşleri").update(ad="Öğrenci İşleri Şube Müdürlüğü")


class Migration(migrations.Migration):
    dependencies = [
        ("dozaj", "0002_branslar_ve_birim"),
        ("core", "0006_kisayol"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
