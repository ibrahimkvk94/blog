"""Program Hazırlama birimi, Sınav Planları bağlantısı ve modüldeki tek kurum."""

from django.conf import settings
from django.db import migrations


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Institution = apps.get_model("timetable", "Institution")
    if not Institution.objects.exists():
        Institution.objects.create(name=settings.KURUM_ADI)

    plan = Birim.objects.filter(slug="plan-program").first()
    if plan is not None and not Birim.objects.filter(slug="program-hazirlama").exists():
        # Ders Planları'nın kardeşi: onun altına eklenirse Ders Planları menüde açılır gruba dönüşürdü
        ders = Birim.objects.filter(slug="ders-planlari").first()
        Birim.objects.create(
            slug="program-hazirlama", ad="Program Hazırlama", ust=plan, tur="gorev", ikon="grid-3x3-gap",
            sira=(ders.sira + 5) if ders else 15, durum="kullanimda", modul_url="timetable:school_list",
            aciklama="Haftalık ders programının hazırlanması ve otomatik üretimi, etkinlik/telafi ve derslik ayırma, "
                     "girişsiz web yayını. Yayınlanan program Ders Planları'na taslak sürüm olarak aktarılır.",
        )
    sinav = Birim.objects.filter(slug="sinav-planlari", modul_url="").first()
    if sinav is not None:
        sinav.modul_url = "dersprogrami_kopru:sinavlar"
        sinav.durum = "kullanimda"
        sinav.save(update_fields=["modul_url", "durum"])


def geri(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Birim.objects.filter(slug="program-hazirlama", yetkiler__isnull=True).delete()
    Birim.objects.filter(slug="sinav-planlari", modul_url="dersprogrami_kopru:sinavlar").update(modul_url="", durum="sirada")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_baslangic_agaci"),
        ("timetable", "0045_event"),
    ]
    operations = [migrations.RunPython(uygula, geri)]
