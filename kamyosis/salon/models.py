"""Salon durumu: konferans salonu ve amfilerin gün ve saat bazında doluluğu.

Kayıtları yalnız yetkililer (Salon Durumu biriminde Düzenleme) girer; görüntüleme herkese açıktır. Kayıt girilmemiş
saatler müsaittir. Aynı salonda aynı saatlere iki kayıt girilemez.
"""

import datetime

from django.conf import settings
from django.db import models

RENKLER = [
    ("#2f5d8a", "Lacivert"), ("#c2410c", "Turuncu"), ("#15803d", "Yeşil"), ("#7c3aed", "Mor"), ("#be185d", "Pembe"),
    ("#0e7490", "Camgöbeği"), ("#a16207", "Hardal"), ("#b91c1c", "Kırmızı"), ("#475569", "Gri"),
]
# Takvimde gösterilen gün aralığı; tüm gün kaydı bu aralığın tamamını kaplar
GUN_BAS = datetime.time(7, 0)
GUN_BIT = datetime.time(22, 0)


class Salon(models.Model):
    ad = models.CharField("Ad", max_length=80, unique=True)
    kisa = models.CharField("Kısa ad", max_length=12, help_text="Takvimde dar yerlerde görünür, ör. KS, AA.")
    renk = models.CharField("Renk", max_length=7, choices=RENKLER, default="#2f5d8a")
    kapasite = models.PositiveIntegerField("Kapasite", null=True, blank=True)
    aciklama = models.CharField("Açıklama", max_length=200, blank=True)
    sira = models.PositiveSmallIntegerField("Sıra", default=10)
    aktif = models.BooleanField("Kullanımda", default=True)

    class Meta:
        ordering = ["sira", "ad"]
        verbose_name = "Salon"
        verbose_name_plural = "Salonlar"

    def __str__(self):
        return self.ad


class SalonKaydi(models.Model):
    """Salonun dolu olduğu zaman: bir günün belli saatleri ya da tüm günü. Haftalık tekrarlanan kayıtlar aynı seri
    kimliğini taşır (seri birlikte silinebilir)."""

    salon = models.ForeignKey(Salon, on_delete=models.CASCADE, related_name="kayitlar", verbose_name="Salon")
    tarih = models.DateField("Tarih", db_index=True)
    tum_gun = models.BooleanField("Tüm gün", default=False)
    bas = models.TimeField("Başlangıç", null=True, blank=True)
    bit = models.TimeField("Bitiş", null=True, blank=True)
    baslik = models.CharField("Başlık", max_length=120, help_text="ör. Kısmın dersi, Mezuniyet provası, Konferans")
    aciklama = models.CharField("Açıklama", max_length=300, blank=True)
    seri = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tarih", "tum_gun", "bas"]
        verbose_name = "Salon kaydı"
        verbose_name_plural = "Salon kayıtları"
        indexes = [models.Index(fields=["salon", "tarih"])]

    def __str__(self):
        return f"{self.salon} · {self.tarih:%d.%m.%Y} {self.saat_metni} · {self.baslik}"

    @property
    def bas_etkin(self):
        return GUN_BAS if self.tum_gun else self.bas

    @property
    def bit_etkin(self):
        return GUN_BIT if self.tum_gun else self.bit

    @property
    def saat_metni(self):
        return "Tüm gün" if self.tum_gun else f"{self.bas:%H:%M}–{self.bit:%H:%M}"

    @property
    def dakika(self):
        b, s = self.bas_etkin, self.bit_etkin
        return max(0, (s.hour * 60 + s.minute) - (b.hour * 60 + b.minute))
