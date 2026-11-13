"""Kullanıcı bildirimleri: sağ üstteki zil listesi ve sağ alttaki kısa süreli pencereler."""

from django.conf import settings
from django.db import models
from django.utils import timezone


class Bildirim(models.Model):
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bildirimler")
    tur = models.CharField("Tür", max_length=30)
    baslik = models.CharField("Başlık", max_length=150)
    metin = models.CharField("Metin", max_length=400, blank=True)
    url = models.CharField("Adres", max_length=300, blank=True)
    olusturma = models.DateTimeField(default=timezone.now, db_index=True)
    okundu = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-pk"]
        verbose_name = "Bildirim"
        verbose_name_plural = "Bildirimler"
        indexes = [models.Index(fields=["kullanici", "okundu"], name="bildirim_okunmamis")]

    def __str__(self):
        return f"{self.kullanici} · {self.baslik}"


class BildirimTercihi(models.Model):
    """Kullanıcının bir bildirim türü için seçimi. Kayıt yoksa "açık"."""

    ACIK, SESSIZ, KAPALI = "acik", "sessiz", "kapali"
    MODLAR = [(ACIK, "Açık"), (SESSIZ, "Sessiz"), (KAPALI, "Kapalı")]

    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bildirim_tercihleri")
    tur = models.CharField("Tür", max_length=30)
    mod = models.CharField("Seçim", max_length=6, choices=MODLAR, default=ACIK)

    class Meta:
        verbose_name = "Bildirim tercihi"
        verbose_name_plural = "Bildirim tercihleri"
        constraints = [models.UniqueConstraint(fields=["kullanici", "tur"], name="bildirim_tercihi_tekil")]


class ZamanliIs(models.Model):
    """Günde bir kez yapılan işlerin (yoklama özeti, eski bildirim temizliği) yapıldı işareti."""

    anahtar = models.CharField(max_length=60, unique=True)
    zaman = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Zamanlı iş"
        verbose_name_plural = "Zamanlı işler"
