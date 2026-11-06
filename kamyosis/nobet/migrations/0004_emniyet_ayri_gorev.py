"""Emniyet Nöbetçi Subaylığı, Bilgisayar Dershaneleri'nden ayrı bir nöbet grubudur.

Mevcut "Bilgisayar Dershaneleri ve Teknik Bloklar Emniyet Nöbetçi Subayı" görevi (kısa adı BİL)
"Bilgisayar Dershaneleri" olarak yeniden adlandırılır, ayarları korunur. Yeni Emniyet Nöbetçi
Subaylığı görevi rütbe kuralı olmadan eklenir; kuralları yönetim panelinden girilir.
"""

from django.db import migrations

ESKI_AD = "Bilgisayar Dershaneleri ve Teknik Bloklar Emniyet Nöbetçi Subayı"


def uygula(apps, schema_editor):
    Gorev = apps.get_model("nobet", "NobetGorevi")
    bil = Gorev.objects.filter(kisa_ad="BİL").first()
    if bil and bil.ad == ESKI_AD:
        bil.ad = "Bilgisayar Dershaneleri"
        bil.save(update_fields=["ad"])
    if not Gorev.objects.filter(kisa_ad="EMN").exists():
        Gorev.objects.create(
            kisa_ad="EMN", ad="Emniyet Nöbetçi Subaylığı", renk="kirmizi", kontenjan=7, yatili=False, puan=1,
            sira=(bil.sira + 5) if bil else 165,
        )


def geri(apps, schema_editor):
    Gorev = apps.get_model("nobet", "NobetGorevi")
    Gorev.objects.filter(kisa_ad="EMN", atamalar__isnull=True).delete()
    Gorev.objects.filter(kisa_ad="BİL", ad="Bilgisayar Dershaneleri").update(ad=ESKI_AD)


class Migration(migrations.Migration):
    dependencies = [("nobet", "0003_nobetayari_yatili_tur_dengesi_and_more")]
    operations = [migrations.RunPython(uygula, geri)]
