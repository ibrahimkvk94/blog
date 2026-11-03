"""Mazeret bildirimleri (PPYS DMS karşılığı; sınav mazereti ileride bu uygulamaya eklenecek).

Ders mazereti: personelin dönem boyunca her hafta geçerli gün × ders saati şablonu.
Hücre değerleri Program Hazırlama modülüyle aynıdır: kayıt yok = uygun (✓),
"no" = ders verilemez (✗), "maybe" = mümkünse verilmesin (?).
Bildirim kaydının olması "bildirildi" demektir; boş şablon = "mazereti yok".
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from personel.models import Personel

YASAK, KOSULLU = "no", "maybe"
DURUMLAR = (YASAK, KOSULLU)
GUN_ADLARI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class DersMazeretDonemi(models.Model):
    ad = models.CharField("Ad", max_length=80, help_text="ör. 2026-2027 Bahar")
    gun_sayisi = models.PositiveSmallIntegerField("Gün sayısı", default=5, help_text="5 = Pazartesi–Cuma")
    saat_sayisi = models.PositiveSmallIntegerField("Ders saati sayısı", default=8)
    giris_acik = models.BooleanField("Bildirime açık", default=True)
    son_bildirim = models.DateTimeField(
        "Son bildirim zamanı", null=True, blank=True,
        help_text="Bu zamandan sonra bölümler değişiklik yapamaz (yöneticiler yapabilir). Boş = süresiz.",
    )
    okul = models.ForeignKey(
        "timetable.School", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Program Hazırlama'daki program",
        help_text="Seçilirse her bildirim bu programdaki öğretmenin müsaitliğine yazılır.",
    )
    aciklama = models.TextField("Bölümlere not", blank=True)
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ders mazeret dönemi"
        verbose_name_plural = "Ders mazeret dönemleri"
        ordering = ["-olusturma"]

    def __str__(self):
        return self.ad

    @property
    def acik_mi(self):
        return self.giris_acik and (self.son_bildirim is None or timezone.now() <= self.son_bildirim)

    @property
    def gunler(self):
        return GUN_ADLARI[: self.gun_sayisi]


class DersMazeretBildirimi(models.Model):
    donem = models.ForeignKey(DersMazeretDonemi, on_delete=models.CASCADE, related_name="bildirimler")
    personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="ders_mazeretleri")
    hucreler = models.JSONField("Mazeretli saatler", default=dict, blank=True,
                                help_text='{"gün-saat": "no" | "maybe"}; gün ve saat 0\'dan başlar.')
    aciklama = models.TextField("Açıklama", blank=True)
    bildiren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)
    surum = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = "Ders mazeret bildirimi"
        verbose_name_plural = "Ders mazeret bildirimleri"
        constraints = [models.UniqueConstraint(fields=["donem", "personel"], name="ders_mazeret_tekil")]

    def __str__(self):
        return f"{self.donem}: {self.personel.ad_soyad}"

    @property
    def yasak_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == YASAK)

    @property
    def kosullu_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == KOSULLU)


class DersMazeretGecmisi(models.Model):
    """Her kaydın anlık görüntüsü (kim, ne zaman, ne bildirdi)."""

    bildirim = models.ForeignKey(DersMazeretBildirimi, on_delete=models.CASCADE, related_name="gecmis")
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now_add=True)
    hucreler = models.JSONField(default=dict)
    aciklama = models.TextField(blank=True)

    class Meta:
        verbose_name = "Bildirim geçmişi"
        verbose_name_plural = "Bildirim geçmişi"
        ordering = ["-zaman"]
