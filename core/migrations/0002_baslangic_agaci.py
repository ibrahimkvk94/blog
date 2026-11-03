"""Başlangıç organizasyon ağacı. Sonraki değişiklikler yönetim panelinden yapılır."""

from django.db import migrations

# (slug, ad, tür, ikon, durum, modül adresi, açıklama, alt birimler)
AGAC = [
    ("ogrenci-isleri-sube", "Öğrenci İşleri Şube Müdürlüğü", "sube", "mortarboard", "planlandi", "", "", [
        ("plan-program", "Plan Program Kısmı", "kisim", "calendar3", "planlandi", "",
         "Ders ve sınav planlarının hazırlanması, belge isteklerinin karşılanması.", [
            ("ders-planlari", "Ders Planları", "gorev", "journal-text", "sirada", "",
             "Ders yükü dağıtımı, haftalık ders programı (Excel'den aktarım ve yayın), ders takibi "
             "(yapıldı beyanı, teyit, devir talepleri), haftalık ders saati mazeretleri ve branş atamaları.\n"
             "PPYS karşılığı: DPS, DDS, DMS, BDD modülleri.", []),
            ("sinav-planlari", "Sınav Planları", "gorev", "clipboard-check", "sirada", "",
             "Sınav oturumları, salonlar, öğrenci yerleşimi, gözetmen ataması, sınav dönemi mazeret "
             "bildirimleri ve sınav görevine katılım.\nPPYS karşılığı: SPS, SMS, STS modülleri.", []),
            ("belge-istekleri", "Belge İstekleri", "gorev", "file-earmark-text", "planlandi", "",
             "Öğrenci ve personel belge taleplerinin alınması, takibi ve sonuçlandırılması.", []),
        ]),
        ("olcme-degerlendirme", "Ölçme Değerlendirme Kısmı", "kisim", "bar-chart-line", "planlandi", "",
         "Sınavların icrası, not girişi ve öğrenci başarılarının değerlendirilmesi.", [
            ("sinav-icrasi", "Sınav İcrası", "gorev", "pencil-square", "planlandi", "",
             "Sınav günü işlemleri: yoklama, salon tutanakları, sınav evrakı takibi.", []),
            ("not-takibi", "Notların Takibi", "gorev", "list-ol", "planlandi", "",
             "Ders bazında not girişi, ilan ve itiraz süreçleri.", []),
            ("basari-siralama", "Öğrenci Başarıları / Sıralamaları", "gorev", "trophy", "planlandi", "",
             "Ortalama hesapları, sınıf ve bölüm sıralamaları, başarı raporları.", []),
        ]),
        ("ogrenci-isleri-kismi", "Öğrenci İşleri Kısmı", "kisim", "people", "planlandi", "",
         "Öğrenci kayıt ve özlük işlemleri, ek ders hesapları.", [
            ("ogrenci-kaydi", "Öğrenci Kaydı", "gorev", "person-plus", "planlandi", "",
             "Öğrenci kimlik ve kayıt bilgileri, durum değişiklikleri.", []),
            ("transkript", "Transkript", "gorev", "file-earmark-ruled", "planlandi", "",
             "Not dökümü ve transkript belgesi üretimi.", []),
            ("siniflandirma", "Sınıflandırma", "gorev", "diagram-3", "planlandi", "",
             "Öğrencilerin sınıf ve şubelere (kısım) dağıtılması.", []),
            ("bolumlere-ayirma", "Bölümlere Ayırma", "gorev", "signpost-split", "planlandi", "",
             "Öğrencilerin tercih ve başarıya göre bölümlere yerleştirilmesi.", []),
            ("ek-ders", "Ek Ders Hesaplamaları", "gorev", "calculator", "planlandi", "",
             "Ders takibindeki yapıldı/teyit kayıtlarından ek ders ücret hesapları ve raporları.", []),
        ]),
    ]),
    ("idari-isler", "İdari İşler", "sube", "building", "planlandi", "", "", [
        ("nobet-faaliyetleri", "Nöbet Faaliyetleri", "gorev", "shield-check", "planlandi", "",
         "Nöbet çizelgeleri, nöbet devir teslim ve olay kayıtları.", []),
        ("nobet-gruplari", "Nöbet Grupları", "gorev", "people-fill", "planlandi", "",
         "Nöbet gruplarının oluşturulması ve personel atamaları.", []),
        ("personel-bilgileri", "Personel Bilgilerini Yönetme", "gorev", "person-vcard", "kullanimda",
         "personel:liste", "Personel kayıtları, bölüm, rütbe, sınıf ve unvan bilgileri.", []),
    ]),
]


def ekle(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")

    def kaydet(dugumler, ust):
        for sira, (slug, ad, tur, ikon, durum, modul_url, aciklama, cocuklar) in enumerate(dugumler, start=1):
            b = Birim.objects.create(
                slug=slug, ad=ad, tur=tur, ikon=ikon, durum=durum, modul_url=modul_url,
                aciklama=aciklama, ust=ust, sira=sira * 10,
            )
            kaydet(cocuklar, b)

    kaydet(AGAC, None)


def sil(apps, schema_editor):
    Birim = apps.get_model("core", "Birim")
    # Alttan üste doğru sil (PROTECT nedeniyle)
    while Birim.objects.exists():
        Birim.objects.filter(alt_birimler__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(ekle, sil)]
