"""Haftalık ders programı (aSc Timetables XML kaynaklı).

Tanımlar (ders, kısım, grup, derslik, öğretmen) sürümler arasında ortaktır ve
aSc kimliğiyle güncellenir. Her XML yüklemesi yeni bir ProgramSurumu oluşturur;
haftalık dersler ve program hücreleri sürüme aittir.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from personel.models import Bolum, Personel

GUNLER = [(1, "Pazartesi"), (2, "Salı"), (3, "Çarşamba"), (4, "Perşembe"), (5, "Cuma"), (6, "Cumartesi"), (7, "Pazar")]


class Derslik(models.Model):
    ad = models.CharField("Ad", max_length=120, unique=True)
    kapasite = models.PositiveIntegerField("Kapasite", null=True, blank=True)
    aktif = models.BooleanField("Aktif", default=True)
    asc_id = models.CharField("aSc kimliği", max_length=40, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Derslik"
        verbose_name_plural = "Derslikler"
        ordering = ["ad"]

    def __str__(self):
        return self.ad


class Ders(models.Model):
    kod = models.CharField("Ders kodu", max_length=30, unique=True)
    ad = models.CharField("Ders adı", max_length=200)
    bolum = models.ForeignKey(Bolum, on_delete=models.SET_NULL, null=True, blank=True, related_name="dersler", verbose_name="Bölüm")
    sinif = models.PositiveSmallIntegerField("Sınıf", null=True, blank=True, help_text="Ders kodundaki ilk rakam (1xx → 1. sınıf).")
    asc_id = models.CharField("aSc kimliği", max_length=40, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Ders"
        verbose_name_plural = "Dersler"
        ordering = ["kod"]

    def __str__(self):
        return f"{self.kod} {self.ad}"


class Kisim(models.Model):
    NORMAL, KREDI, HAZIRLIK = "normal", "kredi", "hazirlik"
    TUR_SECENEKLERI = [
        (NORMAL, "Normal"),
        (KREDI, "Kredi tamamlama"),
        (HAZIRLIK, "Hazırlık"),
    ]

    kod = models.CharField("Kısa kod", max_length=30, unique=True, help_text="ör. 1SVN")
    tur = models.CharField(
        "Tür", max_length=10, choices=TUR_SECENEKLERI, default=NORMAL,
        help_text="Kredi tamamlama: eskiden alınmış bir dersin, öğrencinin mevcut programındaki "
                  "eşleşen dersle aynı saatte verildiği kısım. Hazırlık: yabancı öğrencilerin Türkçe hazırlık kısmı.",
    )
    ad = models.CharField("Ad", max_length=60, help_text="ör. 1.KISIM")
    bolum = models.ForeignKey(Bolum, on_delete=models.SET_NULL, null=True, blank=True, related_name="kisimlar", verbose_name="Bölüm")
    sinif = models.PositiveSmallIntegerField("Sınıf", null=True, blank=True)
    asc_id = models.CharField("aSc kimliği", max_length=40, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Kısım"
        verbose_name_plural = "Kısımlar"

    def __str__(self):
        return self.kod

    @property
    def sira_no(self):
        rakam = "".join(ch for ch in self.kod if ch.isdigit())
        return int(rakam) if rakam else 0


class Grup(models.Model):
    kisim = models.ForeignKey(Kisim, on_delete=models.CASCADE, related_name="gruplar", verbose_name="Kısım")
    ad = models.CharField("Ad", max_length=60)
    tum_kisim = models.BooleanField("Tüm kısım", default=False)
    bolunme = models.CharField("Bölünme", max_length=10, blank=True, help_text="Aynı bölünmedeki gruplar birbirini tamamlar.")
    asc_id = models.CharField("aSc kimliği", max_length=40, unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Grup"
        verbose_name_plural = "Gruplar"
        constraints = [models.UniqueConstraint(fields=["kisim", "ad"], name="grup_kisim_ad_tekil")]

    def __str__(self):
        return self.ad if self.tum_kisim else f"{self.kisim} {self.ad}"


class ProgramOgretmeni(models.Model):
    """aSc'deki öğretmen kaydı ve KAMYOSİS personeliyle eşleşmesi."""

    BEKLIYOR, OTOMATIK, ELLE, YENI, YOK_SAY = "bekliyor", "otomatik", "elle", "yeni", "yoksay"
    DURUM_SECENEKLERI = [
        (BEKLIYOR, "Eşleştirme bekliyor"),
        (OTOMATIK, "Otomatik eşleşti"),
        (ELLE, "Elle eşleştirildi"),
        (YENI, "Yeni personel olarak eklendi"),
        (YOK_SAY, "Yok sayıldı"),
    ]

    ad = models.CharField("aSc'deki adı", max_length=120)
    kisa_ad = models.CharField("aSc kısa adı", max_length=60, blank=True)
    personel = models.ForeignKey(Personel, on_delete=models.SET_NULL, null=True, blank=True, related_name="program_kayitlari", verbose_name="Personel")
    durum = models.CharField("Durum", max_length=10, choices=DURUM_SECENEKLERI, default=BEKLIYOR)
    tahmini_bolum = models.ForeignKey(Bolum, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="Tahmini bölüm")
    asc_id = models.CharField("aSc kimliği", max_length=40, unique=True, null=True, blank=True, editable=False)
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Program öğretmeni"
        verbose_name_plural = "Program öğretmenleri"
        ordering = ["ad"]

    def __str__(self):
        return self.personel.ad_soyad if self.personel_id else self.ad


class ProgramSurumuQuerySet(models.QuerySet):
    def gecerli(self, tarih=None):
        """Verilen tarihte geçerli resmi program: tarihi kapsayan yayındaki sürümlerden en son yayınlanan."""
        tarih = tarih or timezone.localdate()
        return (
            self.filter(durum=ProgramSurumu.YAYINDA, baslangic__lte=tarih)
            .filter(models.Q(bitis__isnull=True) | models.Q(bitis__gte=tarih))
            .order_by("-yayin_zamani", "-pk")
            .first()
        )


class ProgramSurumu(models.Model):
    TASLAK, YAYINDA, ARSIV = "taslak", "yayinda", "arsiv"
    DURUM_SECENEKLERI = [(TASLAK, "Taslak"), (YAYINDA, "Yayında"), (ARSIV, "Arşiv")]

    ad = models.CharField("Ad", max_length=120)
    durum = models.CharField("Durum", max_length=10, choices=DURUM_SECENEKLERI, default=TASLAK)
    baslangic = models.DateField("Geçerlilik başlangıcı", null=True, blank=True)
    bitis = models.DateField("Geçerlilik bitişi", null=True, blank=True)
    kaynak_dosya = models.CharField("Kaynak dosya", max_length=255, blank=True)
    yukleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    yukleme_zamani = models.DateTimeField("Yükleme zamanı", auto_now_add=True)
    yayinlayan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    yayin_zamani = models.DateTimeField("Yayın zamanı", null=True, blank=True)
    aciklama = models.TextField("Açıklama", blank=True)

    objects = ProgramSurumuQuerySet.as_manager()

    class Meta:
        verbose_name = "Program sürümü"
        verbose_name_plural = "Program sürümleri"
        ordering = ["-yukleme_zamani"]

    def __str__(self):
        return self.ad


class DersSaati(models.Model):
    surum = models.ForeignKey(ProgramSurumu, on_delete=models.CASCADE, related_name="ders_saatleri")
    no = models.PositiveSmallIntegerField("Ders saati")
    baslangic = models.TimeField("Başlangıç", null=True, blank=True)
    bitis = models.TimeField("Bitiş", null=True, blank=True)

    class Meta:
        ordering = ["no"]
        constraints = [models.UniqueConstraint(fields=["surum", "no"], name="ders_saati_tekil")]

    def __str__(self):
        return f"{self.no}. saat"


class HaftalikDers(models.Model):
    """aSc'deki "lesson": bir kısım(lar)ın bir dersi, öğretmenleri ve haftalık saati."""

    surum = models.ForeignKey(ProgramSurumu, on_delete=models.CASCADE, related_name="dersler")
    ders = models.ForeignKey(Ders, on_delete=models.PROTECT, related_name="haftalik_dersler")
    kisimlar = models.ManyToManyField(Kisim, related_name="haftalik_dersler")
    gruplar = models.ManyToManyField(Grup, blank=True, related_name="haftalik_dersler")
    ogretmenler = models.ManyToManyField(ProgramOgretmeni, blank=True, related_name="haftalik_dersler")
    haftalik_saat = models.DecimalField("Haftalık saat", max_digits=5, decimal_places=2)
    blok = models.PositiveSmallIntegerField("Blok (ardışık saat)", default=1)
    asc_id = models.CharField("aSc kimliği", max_length=40, blank=True)

    class Meta:
        verbose_name = "Haftalık ders"
        verbose_name_plural = "Haftalık dersler"

    def __str__(self):
        return str(self.ders)


class ProgramHucresi(models.Model):
    """Programa yerleşmiş bir ders saati (aSc "card")."""

    surum = models.ForeignKey(ProgramSurumu, on_delete=models.CASCADE, related_name="hucreler")
    haftalik_ders = models.ForeignKey(HaftalikDers, on_delete=models.CASCADE, related_name="hucreler")
    gun = models.PositiveSmallIntegerField("Gün", choices=GUNLER)
    saat = models.PositiveSmallIntegerField("Ders saati")
    derslik = models.ForeignKey(Derslik, on_delete=models.SET_NULL, null=True, blank=True, related_name="hucreler")

    class Meta:
        verbose_name = "Program hücresi"
        verbose_name_plural = "Program hücreleri"
        indexes = [models.Index(fields=["surum", "gun", "saat"])]

    def __str__(self):
        return f"{self.get_gun_display()} {self.saat}. saat · {self.haftalik_ders}"
