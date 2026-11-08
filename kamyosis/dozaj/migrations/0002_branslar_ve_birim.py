"""Başlangıç branşları (2026-2027 tablosundaki sırayla) ve Plan Program Kısmı altında "Dozajmatik" birimi."""

from django.db import migrations

BRANSLAR = [
    ("BEŞERİ VE SOSYAL BİLİMLER", "TARİH"), ("BEŞERİ VE SOSYAL BİLİMLER", "HUKUK"),
    ("BEŞERİ VE SOSYAL BİLİMLER", "TÜRK DİLİ"),
    ("TEMEL BİLİMLER", "MATEMATİK"), ("TEMEL BİLİMLER", "FİZİK"),
    ("İŞLETME YÖNETİMİ", "İSTATİSTİK"), ("İŞLETME YÖNETİMİ", "İŞLETME"), ("İŞLETME YÖNETİMİ", "İKTİSAT"),
    ("YABANCI", "YABANCI"), ("ELEKTRİK", "ELEKTRİK"), ("ELEKTRONİK", "ELEKTRONİK"), ("BİLGİSAYAR", "BİLGİSAYAR"),
    ("OTOMOTİV", "OTOMOTİV"), ("MEKATRONİK", "MEKATRONİK"), ("UÇAK", "UÇAK"), ("YAPI TESİSAT", "YAPI TESİSAT"),
    ("İNŞAAT", "İNŞAAT"), ("ASKERİ", "ASKERİ"),
    ("SAVUNMA HİZMETLERİ", "SAVUNMA"), ("SAVUNMA HİZMETLERİ", "İSTATİSTİK SVN"), ("SAVUNMA HİZMETLERİ", "SAĞLIK"),
    ("SAVUNMA HİZMETLERİ", "ULUSLARASI"),
]


def uygula(apps, schema_editor):
    Brans = apps.get_model("dozaj", "Brans")
    for i, (grup, ad) in enumerate(BRANSLAR, 1):
        Brans.objects.get_or_create(ad=ad, defaults={"grup": grup, "sira": i * 10, "hesapta": True})
    Brans.objects.get_or_create(ad="AFET", defaults={"grup": "DİĞER", "sira": 900, "hesapta": False})
    Birim = apps.get_model("core", "Birim")
    plan = Birim.objects.filter(slug="plan-program").first()
    if not Birim.objects.filter(slug="dozajmatik").exists():
        Birim.objects.create(
            slug="dozajmatik", ad="Dozajmatik", ust=plan, tur="gorev", ikon="calculator", sira=12,
            durum="kullanimda", modul_url="dozaj:tablo",
            aciklama="Öğretim programları ve kısım sayılarından branş başına ders yükü ve öğretim elemanı ihtiyacı.")


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(slug="dozajmatik").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dozaj", "0001_initial"),
        ("core", "0004_kadro_kapasitesi"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
