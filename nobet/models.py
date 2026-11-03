"""Aylık nöbet grupları (EK-3) ve yıllık puantaj.

Her ay için bir NobetDonemi açılır; personel kurallara göre nöbet görevlerine
dağıtılır (NobetAtamasi), elle düzeltilir ve kesinleştirilir. Adalet hesabı
kesinleşmiş aylardan, Ekim'de başlayan "nöbet yılı" içinde yapılır.
"""

from datetime import date

from django.conf import settings
from django.db import models

from personel.models import Personel, Secenek

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


class NobetAyari(models.Model):
    """Tek satırlık genel ayarlar."""

    yil_baslangic_ayi = models.PositiveSmallIntegerField(
        "Nöbet yılının başladığı ay", default=10, help_text="Adalet sayımları bu ayda sıfırlanır (10 = Ekim).",
    )
    yatili_fark_siniri = models.PositiveSmallIntegerField(
        "Yatılı farkı sınırı (ay)", default=1,
        help_text="Aynı rütbedeki iki personelin bir nöbet yılındaki yatılı ay sayıları arasındaki en fazla fark.",
    )
    ardisik_ayni_gorev = models.BooleanField(
        "Arka arkaya aynı göreve yazılabilir", default=False,
        help_text="Kapalıysa, bir önceki ay aynı görevi tutan kişi mümkünse başka göreve yazılır.",
    )
    yatili_tur_dengesi = models.BooleanField(
        "Yatılı görev türlerini dengele", default=True,
        help_text="Yatılı yazılacak kişi, yıl içinde daha az tuttuğu yatılı göreve yazılır (ör. orduevi / bilgisayar).",
    )

    class Meta:
        verbose_name = "Nöbet ayarları"
        verbose_name_plural = "Nöbet ayarları"

    def __str__(self):
        return "Nöbet ayarları"

    @classmethod
    def al(cls):
        return cls.objects.first() or cls.objects.create()


class NobetGorevi(models.Model):
    """EK-3'teki bir sütun: nöbet yeri/türü, kimlerin tutabileceği, kaç kişi."""

    RENKLER = [
        ("mavi", "Mavi (1. sınıf)"), ("turuncu", "Turuncu (2. sınıf)"), ("yesil", "Yeşil"),
        ("kirmizi", "Kırmızı"), ("sari", "Sarı"), ("gri", "Gri"),
    ]

    ad = models.CharField("Görev adı", max_length=150)
    kisa_ad = models.CharField("Kısa ad", max_length=30, help_text="Puantaj tablosunda görünür, ör. AMİR, ORD, 1B3")
    sira = models.PositiveSmallIntegerField("Sıra", default=0)
    renk = models.CharField("Renk", max_length=10, choices=RENKLER, default="mavi")
    kontenjan = models.PositiveSmallIntegerField(
        "Aylık kişi sayısı", null=True, blank=True,
        help_text="Boş bırakılırsa kalan uygun personelin tamamını alır (kalanlar birden çok göreve eşit bölünür).",
    )
    izinli_rutbeler = models.ManyToManyField(
        Secenek, blank=True, limit_choices_to={"tur": Secenek.RUTBE}, related_name="+", verbose_name="Tutabilecek rütbeler",
    )
    yatili = models.BooleanField("Yatılı", default=False)
    puan = models.DecimalField("Puan", max_digits=4, decimal_places=1, default=1,
                               help_text="Bir ay bu görevi tutmanın puantajdaki karşılığı.")
    aciklama = models.CharField("Not", max_length=150, blank=True, help_text="ör. +6 Okul Komutanlığından")
    sabit_uyeler = models.ManyToManyField(
        Personel, blank=True, related_name="sabit_nobet_gorevleri", verbose_name="Sabit görevliler",
        help_text="Her ay önce bu kişiler bu göreve yazılır (ör. yıl boyu Kütüphane, Kadın Kursiyer).",
    )
    sadece_sabit = models.BooleanField(
        "Sadece sabit görevliler", default=False,
        help_text="İşaretliyse bu göreve otomatik dağıtımda başka kimse yazılmaz.",
    )
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Nöbet görevi"
        verbose_name_plural = "Nöbet görevleri"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def ay_kontenjani(self, ay, onbellek=None):
        """Bu ay için kişi sayısı: aylık istisna varsa o, yoksa genel kontenjan."""
        if onbellek is not None:
            return onbellek.get((self.pk, ay), self.kontenjan)
        k = self.ay_kontenjanlari.filter(ay=ay).first()
        return k.kontenjan if k else self.kontenjan


class NobetKontenjani(models.Model):
    """Bir görevin belirli bir aydaki kişi sayısı (ör. Temmuz'da orduevi 16)."""

    gorev = models.ForeignKey(NobetGorevi, on_delete=models.CASCADE, related_name="ay_kontenjanlari")
    ay = models.PositiveSmallIntegerField("Ay", choices=[(i, a) for i, a in enumerate(AYLAR, start=1)])
    kontenjan = models.PositiveSmallIntegerField("Kişi sayısı")

    class Meta:
        verbose_name = "Aylık kontenjan"
        verbose_name_plural = "Aylık kontenjanlar (genelden farklı aylar)"
        ordering = ["ay"]
        constraints = [models.UniqueConstraint(fields=["gorev", "ay"], name="nobet_kontenjan_tekil")]

    def __str__(self):
        return f"{self.gorev.kisa_ad} {AYLAR[self.ay - 1]}: {self.kontenjan}"


class NobetKisitlamasi(models.Model):
    """Personelin belirli bir dönem nöbete yazılamaması (izin, kurs, tayin, YDGG ...).

    Dönemle kesişen her ayda personel nöbet dağıtımına girmez.
    """

    TURLER = [
        ("izin", "İzin"), ("rapor", "Rapor"), ("kurs", "Kurs"), ("gorevlendirme", "Görevlendirme"),
        ("tayin", "Tayin"), ("aciga_alinma", "Açığa alınma"), ("ydgg", "YDGG"), ("yigg", "YİGG"),
        ("muaf", "Muaf"), ("kantin", "Kantin Bşk.lığı"), ("yazilamaz", "Bu ay yazılamaz"), ("diger", "Diğer"),
    ]
    ETIKETLER = {"izin": "İZİN", "rapor": "RAPOR", "kurs": "KURS", "gorevlendirme": "GÖREVL.", "tayin": "TAYİN",
                 "aciga_alinma": "AÇIĞA AL.", "ydgg": "YDGG", "yigg": "YİGG", "muaf": "MUAF", "kantin": "KANTİN",
                 "yazilamaz": "✕", "diger": "✕"}

    personel = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="nobet_kisitlamalari", verbose_name="Personel")
    tur = models.CharField("Tür", max_length=15, choices=TURLER, default="izin")
    baslangic = models.DateField("Başlangıç")
    bitis = models.DateField("Bitiş", null=True, blank=True, help_text="Boşsa süresiz (ör. tayin).")
    aciklama = models.CharField("Açıklama", max_length=150, blank=True)
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Nöbet kısıtlaması"
        verbose_name_plural = "Nöbet kısıtlamaları"
        ordering = ["-baslangic"]

    def __str__(self):
        return f"{self.personel.ad_soyad} · {self.get_tur_display()} · {self.baslangic:%d.%m.%Y}–{self.bitis:%d.%m.%Y}" if self.bitis else \
            f"{self.personel.ad_soyad} · {self.get_tur_display()} · {self.baslangic:%d.%m.%Y}–"

    @property
    def etiket(self):
        return self.ETIKETLER.get(self.tur, "✕")


class NobetDonemi(models.Model):
    TASLAK, KESIN = "taslak", "kesin"
    DURUMLAR = [(TASLAK, "Taslak"), (KESIN, "Kesinleşti")]

    yil = models.PositiveSmallIntegerField("Yıl")
    ay = models.PositiveSmallIntegerField("Ay")
    durum = models.CharField("Durum", max_length=6, choices=DURUMLAR, default=TASLAK)
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    son_dagitim = models.DateTimeField("Son otomatik dağıtım", null=True, blank=True)
    kesinlestiren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kesin_zamani = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Nöbet ayı"
        verbose_name_plural = "Nöbet ayları"
        ordering = ["-yil", "-ay"]
        constraints = [models.UniqueConstraint(fields=["yil", "ay"], name="nobet_donemi_tekil")]

    def __str__(self):
        return f"{AYLAR[self.ay - 1]} {self.yil}"

    @property
    def ilk_gun(self):
        return date(self.yil, self.ay, 1)

    @property
    def sira_no(self):
        return self.yil * 12 + self.ay - 1

    def nobet_yili(self, baslangic_ayi=None):
        """Bu ayın ait olduğu nöbet yılının ilk ayı: (yıl, ay)."""
        b = baslangic_ayi or NobetAyari.al().yil_baslangic_ayi
        return (self.yil, b) if self.ay >= b else (self.yil - 1, b)


class NobetAtamasi(models.Model):
    donem = models.ForeignKey(NobetDonemi, on_delete=models.CASCADE, related_name="atamalar")
    gorev = models.ForeignKey(NobetGorevi, on_delete=models.PROTECT, related_name="atamalar")
    personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="nobet_atamalari")
    kilitli = models.BooleanField("Elle düzenlendi", default=False,
                                  help_text="Kilitli atamalar otomatik dağıtım yeniden çalıştırılınca korunur.")

    class Meta:
        verbose_name = "Nöbet ataması"
        verbose_name_plural = "Nöbet atamaları"
        constraints = [models.UniqueConstraint(fields=["donem", "personel"], name="nobet_ayda_tek_gorev")]

    def __str__(self):
        return f"{self.donem} · {self.gorev.kisa_ad} · {self.personel.ad_soyad}"
