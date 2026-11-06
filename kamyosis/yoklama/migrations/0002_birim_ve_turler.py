"""İdari İşler altında "Personel Yoklaması" birimi ve başlangıç izin türleri (idari işler yetkilisi değiştirebilir)."""

from django.db import migrations

TURLER = [
    ("Yıllık izin", "Yİ", "#2f5d8a", 10),
    ("Mazeret izni", "Mİ", "#0e7490", 20),
    ("Raporlu", "RP", "#b91c1c", 30),
    ("Görevli", "GRV", "#15803d", 40),
    ("Kurs / eğitim", "KRS", "#7c3aed", 50),
    ("Sevkli", "SVK", "#be185d", 60),
    ("Nöbet izni", "Nİ", "#a16207", 70),
    ("Diğer", "DGR", "#475569", 90),
]


def kur(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    idari = Birim.objects.filter(slug="idari-isler").first()
    if idari is not None:
        Birim.objects.update_or_create(slug="personel-yoklamasi", defaults={
            "ad": "Personel Yoklaması", "ust": idari, "tur": "gorev", "sira": 40, "ikon": "person-check",
            "durum": "kullanimda", "modul_url": "yoklama:ana",
            "aciklama": "Günlük personel yoklaması: izinli, raporlu, görevli gibi durumlar tarih-saat aralığıyla girilir; "
                        "herkes varsayılan olarak mevcuttur. Bölümler kendi personelini girer ve günün yoklamasını "
                        "verir; idari işler yetkilisi tüm bölümleri görür, rapor alır, izin türlerini yönetir.",
        })
    IzinTuru = apps.get_model("yoklama", "IzinTuru")
    for ad, kisa, renk, sira in TURLER:
        IzinTuru.objects.get_or_create(ad=ad, defaults={"kisa": kisa, "renk": renk, "sira": sira})


def geri_al(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="personel-yoklamasi").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("yoklama", "0001_initial"),
        ("core", "0003_bolum_menusu"),
    ]

    operations = [migrations.RunPython(kur, geri_al)]
