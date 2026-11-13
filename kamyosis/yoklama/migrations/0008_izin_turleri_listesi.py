"""İzin türleri, İdari İşler'in listesine göre (09.11.2026). "(Öğleden Önce)" / "(Öğleden Sonra)" ve saatli varyantlar
ayrı tür değildir: türde "yarım gün alınabilir" ve "hazır saatler" ile seçilir. "Gi (kaldırıldı)" alınmadı.

Eski türler yeni adlarına taşınır (kayıtları korunur); listede karşılığı olmayanlar kullanılmamışsa silinir, kullanılmışsa
kapatılır."""

from django.db import migrations

RENK = {"izin": "#2f5d8a", "saglik": "#b91c1c", "aile": "#be185d", "gorev": "#15803d", "egitim": "#7c3aed",
        "adli": "#475569"}

# (ad, kısaltma, grup, yarım gün, hazır saatler, renk — boşsa grubun rengi)
TURLER = [
    ("Yıllık İzin", "Yİ", "izin", False, "", ""),
    ("Yıllık İzin (TMİ)", "TMİ", "izin", False, "", ""),
    ("Yıllık Mazeret İzni", "Mİ", "izin", False, "", "#0e7490"),
    ("Günlük İzin", "Gİ", "izin", True, "", "#b45309"),
    ("İdari İzin", "İDİ", "izin", False, "", ""),
    ("Mehil İzni", "MHL", "izin", False, "", ""),
    ("Ücretsiz İzin", "ÜCİ", "izin", False, "", ""),
    ("Refakat İzni", "RFK", "izin", False, "", ""),
    ("Bakım İzni", "BKM", "izin", False, "", ""),
    ("Sendika Yönetici İzni", "SND", "izin", True, "", ""),
    ("Tabii Afet İzni", "AFT", "izin", False, "", ""),
    ("Hastane", "HST", "saglik", True, "", ""),
    ("Hastane Yatış", "HYT", "saglik", False, "", ""),
    ("İstirahat", "İST", "saglik", False, "", ""),
    ("Sıhhi İzinli", "SIH", "saglik", False, "", ""),
    ("Nöbet İstirahati", "Nİ", "saglik", False, "", "#a16207"),
    ("Evlilik İzni", "EVL", "aile", False, "", ""),
    ("Doğum İzni", "DĞM", "aile", False, "", ""),
    ("Doğum Ön. İz.", "DÖİ", "aile", False, "", ""),
    ("Doğum Son.İz.", "DSİ", "aile", False, "", ""),
    ("Süt İzni", "SÜT", "aile", True, "14:00-15:30, 14:00-17:00, 15:30-17:00", ""),
    ("Babalık İzni", "BBL", "aile", False, "", ""),
    ("Ölüm İzni", "ÖLM", "aile", False, "", ""),
    ("Birlik İçi Görev", "BİG", "gorev", False, "", ""),
    ("Yurtiçi Görev", "YİG", "gorev", False, "", ""),
    ("Yurtdışı Görev", "YDG", "gorev", False, "", ""),
    ("Eğitim İzni", "EĞİ", "egitim", True, "", ""),
    ("Kurs", "KRS", "egitim", False, "", ""),
    ("Yüksek İhtisas", "YİH", "egitim", False, "", ""),
    ("Öz.Eğt.İzn.", "ÖEİ", "egitim", True, "", ""),
    ("Açığa Alınma", "AÇK", "adli", False, "", ""),
    ("Görv. Uzaklaşt.", "GUZ", "adli", False, "", ""),
    ("Aç.Al./Tutuklu", "AÇT", "adli", False, "", ""),
    ("Tutuklu", "TTK", "adli", False, "", ""),
    ("Gözaltı", "GZL", "adli", False, "", ""),
    ("Adli", "ADL", "adli", False, "", ""),
    ("Mahkeme", "MHK", "adli", True, "", ""),
    ("Adli İşlem İzni", "Aİİ", "adli", True, "", ""),
    ("KHK İhraç", "KHK", "adli", False, "", ""),
    ("TSK'dan İhraç", "TSK", "adli", False, "", ""),
    ("Katılış Yapmadı", "KYP", "adli", False, "", ""),
]
# eski ad → yeni ad (kayıtlar, yıllık hak ve rapor sırası korunur)
ESKI = {"Yıllık izin": "Yıllık İzin", "Mazeret izni": "Yıllık Mazeret İzni", "Günlük izin": "Günlük İzin",
        "Raporlu": "İstirahat", "Sevkli": "Hastane", "Görevli": "Yurtiçi Görev", "Kurs / eğitim": "Kurs",
        "Nöbet izni": "Nöbet İstirahati"}


def uygula(apps, schema_editor):
    IzinTuru = apps.get_model("yoklama", "IzinTuru")
    for eski, yeni in ESKI.items():
        t = IzinTuru.objects.filter(ad=eski).first()
        if t is not None and not IzinTuru.objects.filter(ad=yeni).exists():
            t.ad = yeni
            t.save(update_fields=["ad"])
    adlar = set()
    for sira, (ad, kisa, grup, yarim, saatler, renk) in enumerate(TURLER, 1):
        adlar.add(ad)
        t = IzinTuru.objects.filter(ad=ad).first() or IzinTuru(ad=ad)
        t.kisa, t.grup, t.yarim_gun, t.hazir_saatler = kisa, grup, yarim, saatler
        t.renk = renk or RENK[grup]
        t.sira, t.aktif = sira * 10, True
        t.save()
    for t in IzinTuru.objects.exclude(ad__in=adlar):  # listede olmayanlar (Garnizon terk, Diğer …)
        if t.kayitlar.exists():
            t.aktif, t.grup = False, "diger"
            t.save(update_fields=["aktif", "grup"])
        else:
            t.delete()


class Migration(migrations.Migration):
    dependencies = [("yoklama", "0007_tur_grubu")]
    operations = [migrations.RunPython(uygula, migrations.RunPython.noop)]
