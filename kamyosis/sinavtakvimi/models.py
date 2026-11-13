"""Yayınlanan sınav planları (ara sınav, final …): okulun Excel planı yüklenir, yayınlanınca giriş yapan herkes görür."""

from django.conf import settings
from django.db import models


class Takvim(models.Model):
    ad = models.CharField("Ad", max_length=200, help_text="ör. 2026-2027 1. Yarıyıl Ara Sınav Planı")
    aciklama = models.CharField("Açıklama", max_length=300, blank=True)
    yayinda = models.BooleanField("Yayında", default=False)
    yayin_zamani = models.DateTimeField(null=True, blank=True)
    yayinlayan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-olusturma"]
        verbose_name = "Sınav takvimi"
        verbose_name_plural = "Sınav takvimleri"

    def __str__(self):
        return self.ad


class Satir(models.Model):
    """Planın bir satırı: bir program (bölüm) için bir sınav."""

    takvim = models.ForeignKey(Takvim, on_delete=models.CASCADE, related_name="satirlar")
    tarih = models.DateField("Tarih")
    baslangic = models.TimeField("Başlangıç")
    bitis = models.TimeField("Bitiş", null=True, blank=True)
    sinif = models.PositiveSmallIntegerField("Sınıf", null=True, blank=True)
    ders = models.CharField("Ders adı", max_length=200)
    kod = models.CharField("Ders kodu", max_length=20, blank=True)
    bolum = models.CharField("Bölüm / program", max_length=20, blank=True)
    tur = models.CharField("Sınav türü", max_length=60, blank=True)
    sira = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["tarih", "baslangic", "sira"]
        verbose_name = "Sınav satırı"
        verbose_name_plural = "Sınav satırları"

    def __str__(self):
        return f"{self.tarih:%d.%m.%Y} {self.baslangic:%H.%M} {self.kod} {self.bolum}"


class Malzeme(models.Model):
    """Sınavda kullanılacak malzeme: planın bir ders × program satırı için (satırlar plan yenilense de kod ve programa
    bağlı kalır). Seçilenler virgüllü kod listesi (servis.MALZEMELER); "yok" açıkça malzeme kullanılmayacağını söyler."""

    takvim = models.ForeignKey(Takvim, on_delete=models.CASCADE, related_name="malzemeler")
    kod = models.CharField("Ders kodu", max_length=20)
    bolum = models.CharField("Sınavın yapılacağı program", max_length=20)
    secimler = models.CharField(max_length=100, blank=True)
    diger = models.CharField("Diğer", max_length=120, blank=True)
    yok = models.BooleanField("Malzeme yok", default=False)
    sure = models.PositiveSmallIntegerField("Sınav süresi (dk)", null=True, blank=True)
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sınav malzemesi"
        verbose_name_plural = "Sınav malzemeleri"
        constraints = [models.UniqueConstraint(fields=["takvim", "kod", "bolum"], name="malzeme_tek")]

    def __str__(self):
        return f"{self.kod} {self.bolum}: {self.secimler or ('yok' if self.yok else '')} {self.diger}".strip()


class Etut(models.Model):
    """Sınavdan önceki gün etüde gelecek öğretim elemanı (ders × program başına bir; isteğe bağlı ikincisi)."""

    takvim = models.ForeignKey(Takvim, on_delete=models.CASCADE, related_name="etutler")
    kod = models.CharField("Ders kodu", max_length=20)
    bolum = models.CharField("Sınavın yapılacağı program", max_length=20)
    ogretmen1 = models.ForeignKey("personel.Personel", on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="Öğretim elemanı")
    ogretmen2 = models.ForeignKey("personel.Personel", on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+", verbose_name="2. öğretim elemanı")
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Etüt görevlendirmesi"
        verbose_name_plural = "Etüt görevlendirmeleri"
        constraints = [models.UniqueConstraint(fields=["takvim", "kod", "bolum"], name="etut_tek")]

    def __str__(self):
        return f"{self.kod} {self.bolum}"
