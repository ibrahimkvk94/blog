"""Ekim 2026 EK-3'teki nöbet görevleri ve verilen rütbe kuralları.

- Kd.Öğt.Gör. ve Okul Nöbetçi Amirliği: Yzb., Bnb., Yb.
- Etüt (kat nöbetçi öğretmen) grupları, Bilgisayar Dershaneleri Emniyet ve Orduevi: Ütğm., Tğm.
- Kuralı verilmeyen görevler (Revir, Okul Nö.Sb., Kadın Kursiyer, MYO Md.lüğü) rütbesiz başlar; yönetim panelinden girilir.
Kontenjanlar Ekim listesindeki kişi sayılarıdır; puanlar başlangıç değeridir (yatılı 2, diğer 1).
"""

from django.db import migrations

KIDEMLI = ["Yzb.", "Bnb.", "Yb."]
GENC = ["Ütğm.", "Tğm."]

# (kısa ad, ad, renk, kontenjan, yatılı, puan, rütbeler, not)
GOREVLER = [
    ("KD1", "Kıdemli Öğretim Görevlisi (1'inci Sınıf)", "mavi", 10, False, 1, KIDEMLI, ""),
    ("1B3", "1'inci Sınıf B Blok 3'üncü Kat Nöbetçi Öğretmen", "mavi", 4, False, 1, GENC, ""),
    ("1B2", "1'inci Sınıf B Blok 2'nci Kat Nöbetçi Öğretmen", "mavi", 4, False, 1, GENC, ""),
    ("1B1", "1'inci Sınıf B Blok 1'inci Kat Nöbetçi Öğretmen", "mavi", 4, False, 1, GENC, ""),
    ("1C3", "1'inci Sınıf C Blok 3'üncü Kat Nöbetçi Öğretmen (Kütüphane)", "mavi", 14, False, 1, GENC, ""),
    ("REV", "Revir", "yesil", 6, False, 1, [], "+6 Okul Komutanlığından"),
    ("AMİR", "Okul Nöbetçi Amirliği", "yesil", 5, False, 1, KIDEMLI, ""),
    ("OKSB", "Okul Nöbetçi Subaylığı", "yesil", 2, False, 1, [], "+2 Okul Komutanlığından"),
    ("KAD", "Kadın Kursiyer/Öğrenci Nöbetçi Subaylığı", "yesil", 4, False, 1, [], "+4 Okul Komutanlığından"),
    ("KD2", "Kıdemli Öğretim Görevlisi (2'nci Sınıf)", "turuncu", 4, False, 1, KIDEMLI, ""),
    ("2D2", "2'nci Sınıf D Blok 2'nci Kat Nöbetçi Öğretmen", "turuncu", 4, False, 1, GENC, ""),
    ("2D1", "2'nci Sınıf D Blok 1'inci Kat Nöbetçi Öğretmen", "turuncu", 4, False, 1, GENC, ""),
    ("2D3", "2'nci Sınıf D Blok 3'üncü Kat Nöbetçi Öğretmen", "turuncu", 4, False, 1, GENC, ""),
    ("2C1", "2'nci Sınıf C Blok 1'inci Kat Nöbetçi Öğretmen", "turuncu", 4, False, 1, GENC, ""),
    ("2C2", "2'nci Sınıf C Blok 2'nci Kat Nöbetçi Öğretmen", "turuncu", 4, False, 1, GENC, ""),
    ("BİL", "Bilgisayar Dershaneleri ve Teknik Bloklar Emniyet Nöbetçi Subayı", "kirmizi", 12, True, 2, GENC, ""),
    ("MYO", "MYO Müdürlüğü Nöbetçi Subayı/Astsubayı", "yesil", 13, False, 1, [], ""),
    ("ORD", "Orduevi", "sari", 13, True, 2, GENC, ""),
]


def ekle(apps, schema_editor):
    Gorev = apps.get_model("nobet", "NobetGorevi")
    Secenek = apps.get_model("personel", "Secenek")
    Ayar = apps.get_model("nobet", "NobetAyari")
    Birim = apps.get_model("core", "Birim")
    rutbe = {s.metin: s for s in Secenek.objects.filter(tur="R")}
    for sira, (kisa, ad, renk, kontenjan, yatili, puan, rutbeler, aciklama) in enumerate(GOREVLER, start=1):
        g = Gorev.objects.create(kisa_ad=kisa, ad=ad, renk=renk, kontenjan=kontenjan, yatili=yatili, puan=puan,
                                 aciklama=aciklama, sira=sira * 10)
        g.izinli_rutbeler.set([rutbe[r] for r in rutbeler if r in rutbe])
    if not Ayar.objects.exists():
        Ayar.objects.create(yil_baslangic_ayi=10, yatili_fark_siniri=1)
    Birim.objects.filter(slug="nobet-gruplari").update(modul_url="nobet:ana", durum="kullanimda")


def geri(apps, schema_editor):
    apps.get_model("nobet", "NobetGorevi").objects.all().delete()
    apps.get_model("core", "Birim").objects.filter(slug="nobet-gruplari").update(modul_url="", durum="planlandi")


class Migration(migrations.Migration):
    dependencies = [
        ("nobet", "0001_initial"),
        ("personel", "0006_personel_nobet_durumu_personel_nobet_muafiyet_bitis_and_more"),
        ("core", "0002_baslangic_agaci"),
    ]
    operations = [migrations.RunPython(ekle, geri)]
