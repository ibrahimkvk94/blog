"""Sınav görev puantajı (PPYS STS karşılığı).

SinavGorevi: personelin bir oturumdaki sınav görevi. Sınav Planlama'daki bir sınav dönemi "puantaja işlenince"
o dönemin görevleri anlık görüntü olarak buraya yazılır (sınav sonradan değişirse dönem yeniden işlenir); Sınav
Planlama dışındaki görevler elle eklenir. Hafta içi görev 1, hafta sonu görevi 1,5 puandır.
"""

from django.conf import settings
from django.db import models

from personel.models import Personel

ROLLER = [("A", "Salon amiri"), ("G", "Gözetmen"), ("T", "Taşıyıcı")]


class SinavGorevi(models.Model):
    personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="sinav_gorevleri")
    tarih = models.DateField("Tarih")
    saat = models.CharField("Oturum saati", max_length=5, blank=True)
    rol = models.CharField("Rol", max_length=1, choices=ROLLER, default="G")
    sinav = models.CharField("Sınav", max_length=200, blank=True)
    salon = models.CharField("Salon", max_length=100, blank=True)
    donem_adi = models.CharField("Sınav dönemi", max_length=200, blank=True)
    sinav_donemi = models.ForeignKey(
        "sinav.ExamPeriod", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Puantaja işlenen dönem; elle eklenen görevde boş.",
    )
    elle = models.BooleanField("Elle eklendi", default=False)
    aciklama = models.CharField("Açıklama", max_length=200, blank=True)
    ekleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sınav görevi"
        verbose_name_plural = "Sınav görevleri"
        ordering = ["tarih", "saat", "personel__ad_soyad"]
        indexes = [models.Index(fields=["tarih"])]

    def __str__(self):
        return f"{self.personel.ad_soyad} · {self.tarih:%d.%m.%Y} {self.saat} · {self.get_rol_display()}"

    @property
    def hafta_sonu(self):
        return self.tarih.weekday() >= 5

    @property
    def puan(self):
        return 1.5 if self.hafta_sonu else 1


class IslenenDonem(models.Model):
    """Puantaja işlenmiş sınav dönemi (kim, ne zaman, kaç görev)."""

    sinav_donemi = models.OneToOneField("sinav.ExamPeriod", on_delete=models.CASCADE, related_name="puantaj")
    isleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now=True)
    gorev_sayisi = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Puantaja işlenen sınav dönemi"
        verbose_name_plural = "Puantaja işlenen sınav dönemleri"
