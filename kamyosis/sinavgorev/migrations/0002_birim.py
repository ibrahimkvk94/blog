"""Plan Program altında "Sınav Görev Puantajı" birimi (PPYS STS karşılığı).

Yetki üst birimden miras geçer: bölüm hesapları yalnızca kendi bölümünün puantajını görür.
"""

from django.db import migrations

ESKI = ", sınav dönemi mazeret bildirimleri ve sınav görevine katılım.\nPPYS karşılığı: SPS, SMS, STS modülleri."
YENI = ".\nPPYS karşılığı: SPS. Mazeret bildirimi Mazeretler → Sınav Mazeretleri'nde, görev puantajı Sınav Görev Puantajı'nda."


def kur(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    plan = Birim.objects.filter(slug="plan-program").first()
    if plan is None:
        return
    Birim.objects.update_or_create(slug="sinav-gorev-puantaji", defaults={
        "ad": "Sınav Görev Puantajı", "ust": plan, "tur": "gorev", "sira": 25, "ikon": "clipboard-data",
        "durum": "kullanimda", "modul_url": "sinavgorev:puantaj",
        "aciklama": "Personelin eğitim-öğretim yılı (Ekim'de sıfırlanır) boyunca aldığı sınav görevleri: hafta içi 1, "
                    "hafta sonu 1,5 puan; skor ders yüküyle dengelenir. Görevli rolleri (salon amiri, gözetmen, "
                    "taşıyıcı) buradan belirlenir.\nPPYS karşılığı: STS.",
    })
    for b in Birim.objects.filter(slug="sinav-planlari", aciklama__contains=ESKI):
        b.aciklama = b.aciklama.replace(ESKI, YENI)
        b.save(update_fields=["aciklama"])


def geri_al(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="sinav-gorev-puantaji").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("sinavgorev", "0001_initial"),
        ("core", "0002_baslangic_agaci"),
    ]

    operations = [migrations.RunPython(kur, geri_al)]
