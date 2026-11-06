"""Başlangıç salonları ve Plan Program kısmının altında "Salon Durumu" birimi."""

from django.db import migrations

SALONLAR = [("Konferans Salonu", "KS", "#2f5d8a", 10), ("Atatürk Amfisi", "AA", "#c2410c", 20),
            ("Alparslan Amfisi", "ALP", "#15803d", 30)]


def uygula(apps, schema_editor):
    Salon = apps.get_model("salon", "Salon")
    for ad, kisa, renk, sira in SALONLAR:
        Salon.objects.get_or_create(ad=ad, defaults={"kisa": kisa, "renk": renk, "sira": sira})
    Birim = apps.get_model("core", "Birim")
    plan = Birim.objects.filter(slug="plan-program").first()
    if not Birim.objects.filter(slug="salon-durumu").exists():
        Birim.objects.create(
            slug="salon-durumu", ad="Salon Durumu", ust=plan, tur="gorev", ikon="calendar-week", sira=27,
            durum="kullanimda", modul_url="salon:yil",
            aciklama="Konferans salonu ve amfilerin gün ve saat bazında doluluğu. Kayıtları yetkililer girer, herkes görür.")


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="salon-durumu").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("salon", "0001_initial"),
        ("core", "0003_bolum_menusu"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
