"""Yetki tablosuna üç yeni satır: Ders Takibi ve Devir Talepleri (önceden Ders Planları yetkisine bağlıydı) ve
Organizasyon Şeması (önceden bölüm hesapları dışında herkese açıktı).

Kimsenin erişimi değişmesin diye: Ders Planları'nda doğrudan yetkisi olanlara aynı seviye ve kapsamda Ders Takibi ve
Devir Talepleri yetkisi; menüsünde organizasyon şemasını gören hesaplara (sistem yöneticisi ve bölüm hesabı olmayanlar)
Organizasyon Şeması görüntüleme yetkisi verilir. Canlıda istenen tek hesap istisnası elle uygulandı (adı depoda
tutulmaz; kişi adı içerir)."""

from django.db import migrations

HARIC = set()  # canlıda uygulanan istisna (bir hesap) burada yazılmaz
YENI = [
    # (slug, ad, ikon, sıra, modül adresi, açıklama)
    ("ders-takibi", "Ders Takibi", "check2-square", 10, "takip:gunluk",
     "Günlük ders takibi ve yapılan ders raporu."),
    ("devir-talepleri", "Devir Talepleri", "arrow-left-right", 11, "takip:devirler",
     "Ders devri talebi açma, onay ve iade (kesinleştirme Plan Program Kısmı yönetiminde)."),
]


def uygula(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    Yetki = apps.get_model("core", "Yetki")
    User = apps.get_model("accounts", "User")
    plan = Birim.objects.filter(slug="plan-program").first()
    dp = Birim.objects.filter(slug="ders-planlari").first()
    for slug, ad, ikon, sira, url, aciklama in YENI:
        b, yeni = Birim.objects.get_or_create(slug=slug, defaults={
            "ad": ad, "ust": plan, "tur": "gorev", "ikon": ikon, "sira": sira, "durum": "kullanimda",
            "modul_url": url, "aciklama": aciklama})
        if yeni and dp is not None:
            for y in Yetki.objects.filter(birim=dp).exclude(kullanici__username__in=HARIC):
                Yetki.objects.get_or_create(kullanici_id=y.kullanici_id, birim=b,
                                            defaults={"seviye": y.seviye, "kapsam": y.kapsam})
    org, yeni = Birim.objects.get_or_create(slug="organizasyon-semasi", defaults={
        "ad": "Organizasyon Şeması", "ust": None, "tur": "gorev", "ikon": "diagram-3", "sira": 900,
        "durum": "kullanimda", "modul_url": "core:organizasyon",
        "aciklama": "Birimlerin ağacı ve kullanım durumları."})
    if yeni:
        for u in User.objects.filter(is_active=True, is_superuser=False).exclude(username__in=HARIC):
            tum = Yetki.objects.filter(kullanici=u, kapsam="tum").exists()
            bolum_hesabi = (u.bolum_id is not None or u.teskilat_birimi_id is not None) and not tum
            if not bolum_hesabi:
                # "kendi birimi" kapsamı: hesabın türünü (tüm okul / kişisel) değiştirmez; şema için kapsam önemsiz
                Yetki.objects.get_or_create(kullanici=u, birim=org, defaults={"seviye": 1, "kapsam": "bolum"})


def geri(apps, schema_editor):
    apps.get_model("core", "Birim").objects.filter(
        slug__in=["ders-takibi", "devir-talepleri", "organizasyon-semasi"]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_kadro_kapasitesi"),
        ("accounts", "0007_guvenilir_cihaz"),
    ]

    operations = [migrations.RunPython(uygula, geri)]
