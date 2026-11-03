"""Sınav Mazeretleri birimi kullanıma alınır (PPYS SMS karşılığı)."""

from django.db import migrations


def kullanima_al(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug="sinav-mazeretleri").update(
        durum="kullanimda", modul_url="mazeret:sinav",
        aciklama="Sınav dönemindeki gün × oturumlar için mazeret bildirimi: ✗ görev verilemez, ? mümkünse verilmesin, "
                 "boş = uygun. Bildirimler Sınav Planlama'daki gözetmen dağıtımında kullanılır; bildirimi olmayana "
                 "görev verilmez.\nPPYS karşılığı: SMS.",
    )


def geri_al(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="sinav-mazeretleri").update(durum="planlandi", modul_url="")


class Migration(migrations.Migration):

    dependencies = [
        ("mazeret", "0003_sinav_mazereti"),
        ("core", "0002_baslangic_agaci"),
    ]

    operations = [migrations.RunPython(kullanima_al, geri_al)]
