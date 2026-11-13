"""Ders takibi: yapılan dersler ve devir talepleri.

Tarihli dersler tabloda tutulmaz; yayındaki program sürümünden hesaplanır
(bkz. servis.beklenen_dersler). Tarihi geçen ders kendiliğinden "yapıldı" sayılır;
beyan ve teyit yoktur. Bir derse devir talebi açıldığında o tarih + program hücresi
+ öğretmen için bir DersKaydi oluşturulur.
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from personel.models import Personel
from program.models import ProgramHucresi, ProgramOgretmeni


class AkademikDonem(models.Model):
    ad = models.CharField("Ad", max_length=80, help_text="ör. 2026-2027 Güz")
    baslangic = models.DateField("Başlangıç")
    bitis = models.DateField("Bitiş")

    class Meta:
        verbose_name = "Akademik dönem"
        verbose_name_plural = "Akademik dönemler"
        ordering = ["-baslangic"]

    def __str__(self):
        return self.ad


class Tatil(models.Model):
    tarih = models.DateField("Tarih", unique=True)
    aciklama = models.CharField("Açıklama", max_length=120)

    class Meta:
        verbose_name = "Tatil günü"
        verbose_name_plural = "Tatil günleri"
        ordering = ["tarih"]

    def __str__(self):
        return f"{self.tarih:%d.%m.%Y} {self.aciklama}"


class DersKaydi(models.Model):
    tarih = models.DateField("Tarih")
    hucre = models.ForeignKey(ProgramHucresi, on_delete=models.PROTECT, related_name="kayitlar")
    ogretmen = models.ForeignKey(ProgramOgretmeni, on_delete=models.PROTECT, related_name="ders_kayitlari",
                                 verbose_name="Programdaki öğretmen")

    class Meta:
        verbose_name = "Ders kaydı"
        verbose_name_plural = "Ders kayıtları"
        constraints = [models.UniqueConstraint(fields=["tarih", "hucre", "ogretmen"], name="ders_kaydi_tekil")]
        indexes = [models.Index(fields=["tarih"])]

    def __str__(self):
        return f"{self.tarih:%d.%m.%Y} {self.hucre.saat}. saat {self.hucre.haftalik_ders}"


class DevirTalebi(models.Model):
    TALEP, ONAY, KESIN, IADE, IPTAL = "talep", "onay", "kesin", "iade", "iptal"
    DURUM_SECENEKLERI = [
        (TALEP, "Talep edildi"), (ONAY, "Onaylandı"), (KESIN, "Kesinleşti"), (IADE, "İade edildi"), (IPTAL, "İptal edildi"),
    ]
    ETKIN = (TALEP, ONAY, KESIN)
    BEKLEYEN = (TALEP, ONAY)

    blok = models.UUIDField("Talep grubu", default=uuid.uuid4, db_index=True,
                            help_text="Birlikte talep edilen dersler; kararlar grubun tamamına uygulanır.")
    kayit = models.ForeignKey(DersKaydi, on_delete=models.CASCADE, related_name="devirler")
    yeni_personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="devralinan_dersler", verbose_name="Devralacak personel")
    gerekce = models.TextField("Gerekçe")
    durum = models.CharField("Durum", max_length=6, choices=DURUM_SECENEKLERI, default=TALEP)
    isteyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    istek_zamani = models.DateTimeField(auto_now_add=True)
    onaylayan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    onay_zamani = models.DateTimeField(null=True, blank=True)
    kesinlestiren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    kesin_zamani = models.DateTimeField(null=True, blank=True)
    karar_veren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    karar_zamani = models.DateTimeField(null=True, blank=True)
    karar_notu = models.TextField("Son karar notu", blank=True)

    class Meta:
        verbose_name = "Devir talebi"
        verbose_name_plural = "Devir talepleri"
        ordering = ["-istek_zamani"]
        constraints = [
            models.UniqueConstraint(fields=["kayit"], condition=Q(durum__in=("talep", "onay", "kesin")), name="kayit_tek_etkin_devir"),
        ]

    def __str__(self):
        return f"{self.kayit} → {self.yeni_personel} ({self.get_durum_display()})"


class Gunluk(models.Model):
    """Ders takibi işlem kaydı (kim, ne zaman, ne yaptı)."""

    zaman = models.DateTimeField(auto_now_add=True, db_index=True)
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    islem = models.CharField(max_length=40)
    ayrinti = models.TextField(blank=True)

    class Meta:
        verbose_name = "İşlem kaydı"
        verbose_name_plural = "İşlem kayıtları"
        ordering = ["-zaman"]

    def __str__(self):
        return f"{self.zaman:%d.%m.%Y %H:%M} {self.kullanici} {self.islem}"
