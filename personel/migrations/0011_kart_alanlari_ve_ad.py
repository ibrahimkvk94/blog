""""Personel Bilgilerini Yönetme" → "Personel Kartları" ve başlangıç kart alanları (yöneticiler değiştirebilir)."""

from django.db import migrations

ALANLAR = [
    ("Cep telefonu", "İletişim", "telefon", "", 10),
    ("İş telefonu (dahili)", "İletişim", "telefon", "", 20),
    ("E-posta", "İletişim", "eposta", "", 30),
    ("Ev adresi", "İletişim", "uzun", "", 40),
    ("Acil durumda aranacak kişi", "İletişim", "metin", "", 50),
    ("Acil durum telefonu", "İletişim", "telefon", "", 60),
    ("Doğum tarihi", "Kimlik", "tarih", "", 10),
    ("Doğum yeri", "Kimlik", "metin", "", 20),
    ("Kan grubu", "Kimlik", "secim", "0 Rh+, 0 Rh-, A Rh+, A Rh-, B Rh+, B Rh-, AB Rh+, AB Rh-", 30),
    ("Göreve başlama tarihi", "Görev", "tarih", "", 10),
]


def ileri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="personel-bilgileri").update(ad="Personel Kartları")
    KartAlani = apps.get_model("personel", "KartAlani")
    for ad, grup, tur, secenekler, sira in ALANLAR:
        KartAlani.objects.get_or_create(ad=ad, defaults={"grup": grup, "tur": tur, "secenekler": secenekler,
                                                         "sira": sira})


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="personel-bilgileri").update(ad="Personel Bilgilerini Yönetme")


class Migration(migrations.Migration):

    dependencies = [
        ("personel", "0010_personel_kartlari"),
        ("core", "0003_bolum_menusu"),
    ]

    operations = [migrations.RunPython(ileri, geri)]
