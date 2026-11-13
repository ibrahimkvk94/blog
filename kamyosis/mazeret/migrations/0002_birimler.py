"""Plan Program Kısmı altında "Mazeretler" başlığı: Ders Mazeretleri (kullanımda), Sınav Mazeretleri (planlandı).

Yetki üst birimden miras geçer: Plan Program'da "kendi bölümü" yetkisi olan bölüm hesapları
burada da yalnızca kendi personelini görür.
"""

from django.db import migrations

ESKI = ", haftalık ders saati mazeretleri"


def birimleri_kur(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    plan = Birim.objects.filter(slug="plan-program").first()
    if plan is None:
        return
    grup, _ = Birim.objects.update_or_create(slug="mazeretler", defaults={
        "ad": "Mazeretler", "ust": plan, "tur": "gorev", "sira": 12, "ikon": "calendar-x",
        "durum": "kullanimda", "modul_url": "",
        "aciklama": "Personelin ders ve sınav dönemleri için mazeret bildirimleri. Bölümler kendi personeli için bildirir.",
    })
    Birim.objects.update_or_create(slug="ders-mazeretleri", defaults={
        "ad": "Ders Mazeretleri", "ust": grup, "tur": "gorev", "sira": 10, "ikon": "calendar-week",
        "durum": "kullanimda", "modul_url": "mazeret:ders",
        "aciklama": "Haftalık ders mazeretleri: ✗ ders verilemez, ? mümkünse verilmesin, boş = uygun. "
                    "Bildirimler Program Hazırlama'daki öğretmen müsaitliğine aktarılır.\nPPYS karşılığı: DMS.",
    })
    Birim.objects.update_or_create(slug="sinav-mazeretleri", defaults={
        "ad": "Sınav Mazeretleri", "ust": grup, "tur": "gorev", "sira": 20, "ikon": "calendar2-x",
        "durum": "planlandi", "modul_url": "",
        "aciklama": "Sınav dönemindeki gün ve oturumlar için mazeret bildirimi; gözetmen atamasında kullanılır.\nPPYS karşılığı: SMS.",
    })
    for b in Birim.objects.filter(slug="ders-planlari", aciklama__contains=ESKI):
        b.aciklama = b.aciklama.replace(ESKI, "")
        b.save(update_fields=["aciklama"])


def geri_al(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug__in=["ders-mazeretleri", "sinav-mazeretleri"]).delete()
    Birim.objects.filter(slug="mazeretler").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("mazeret", "0001_initial"),
        ("core", "0002_baslangic_agaci"),
    ]

    operations = [migrations.RunPython(birimleri_kur, geri_al)]
