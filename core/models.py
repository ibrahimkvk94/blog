from django.conf import settings
from django.db import models
from django.urls import reverse


class Birim(models.Model):
    """Organizasyon ağacının bir düğümü: şube, kısım veya görev (modül).

    Menü, panel ve yetkiler bu ağaçtan üretilir; yeni dal eklemek kod gerektirmez.
    """

    SUBE, KISIM, GOREV = "sube", "kisim", "gorev"
    TUR_SECENEKLERI = [(SUBE, "Şube / Birim"), (KISIM, "Kısım"), (GOREV, "Görev / Modül")]

    KULLANIMDA, SIRADA, PLANLANDI = "kullanimda", "sirada", "planlandi"
    DURUM_SECENEKLERI = [
        (KULLANIMDA, "Kullanımda"),
        (SIRADA, "Sıradaki aşama"),
        (PLANLANDI, "Planlandı"),
    ]

    ad = models.CharField("Ad", max_length=120)
    slug = models.SlugField("Adres kodu", max_length=60, unique=True)
    ust = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True,
        related_name="alt_birimler", verbose_name="Üst birim",
    )
    tur = models.CharField("Tür", max_length=10, choices=TUR_SECENEKLERI, default=GOREV)
    sira = models.PositiveIntegerField("Sıra", default=0)
    ikon = models.CharField(
        "İkon", max_length=40, default="folder",
        help_text='Bootstrap Icons adı, ör. "calendar3" (icons.getbootstrap.com).',
    )
    aciklama = models.TextField("Açıklama", blank=True)
    modul_url = models.CharField(
        "Modül adresi", max_length=80, blank=True,
        help_text='Modül hazırsa Django URL adı, ör. "personel:liste". Boşsa birim sayfası açılır.',
    )
    durum = models.CharField("Durum", max_length=12, choices=DURUM_SECENEKLERI, default=PLANLANDI)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Birim"
        verbose_name_plural = "Organizasyon ağacı"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad

    def get_absolute_url(self):
        if self.modul_url:
            return reverse(self.modul_url)
        return reverse("core:birim", args=[self.slug])


class Yetki(models.Model):
    """Bir kullanıcının bir birimdeki yetkisi. Alt birimlere de geçer."""

    GORUNTULEME, DUZENLEME, YONETIM = 1, 2, 3
    SEVIYE_SECENEKLERI = [(GORUNTULEME, "Görüntüleme"), (DUZENLEME, "Düzenleme"), (YONETIM, "Yönetim")]

    TUM, BOLUM = "tum", "bolum"
    KAPSAM_SECENEKLERI = [(TUM, "Tüm bölümler"), (BOLUM, "Sadece kendi bölümü")]

    kullanici = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="yetkiler", verbose_name="Kullanıcı",
    )
    birim = models.ForeignKey(Birim, on_delete=models.CASCADE, related_name="yetkiler", verbose_name="Birim")
    seviye = models.PositiveSmallIntegerField("Seviye", choices=SEVIYE_SECENEKLERI, default=GORUNTULEME)
    kapsam = models.CharField("Kapsam", max_length=5, choices=KAPSAM_SECENEKLERI, default=TUM)

    class Meta:
        verbose_name = "Yetki"
        verbose_name_plural = "Yetkiler"
        constraints = [models.UniqueConstraint(fields=["kullanici", "birim"], name="yetki_kullanici_birim_tekil")]

    def __str__(self):
        return f"{self.kullanici} → {self.birim} ({self.get_seviye_display()})"
