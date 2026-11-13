"""İdari İşler altında "Müsait Personel" birimi (yetki tablosunda ayrı satır; yetki elle verilir)."""

from django.db import migrations


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    ust = Birim.objects.filter(slug="idari-isler").first()
    Birim.objects.get_or_create(slug="musait-personel", defaults={
        "ad": "Müsait Personel", "ust": ust, "tur": "gorev", "ikon": "person-check-fill", "sira": 42,
        "durum": "kullanimda", "modul_url": "yoklama:musait",
        "aciklama": "Seçilen gün ve saatlerde okulda olan, izinli olmayan, dersi ve sınav görevi bulunmayan personel."})


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="musait-personel").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("yoklama", "0005_izin_haklari"),
        ("core", "0005_ders_takibi_devir_organizasyon"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
