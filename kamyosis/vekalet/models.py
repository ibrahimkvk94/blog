"""Vekâlet: personel raporlu, izinli ya da görevliyken görevini (yetkilerini) kime, hangi tarihler arasında bıraktığı.
Kaydı İdari İşler girer; "Vekâletler" sekmesi yetki verilen herkese kimin kime vekâlet ettiğini gösterir."""

from django.conf import settings
from django.db import models
from django.utils import timezone

from personel.models import Personel


class Vekalet(models.Model):
    RAPOR, IZIN, GOREV, KURS, DIGER = "rapor", "izin", "gorev", "kurs", "diger"
    NEDENLER = [(RAPOR, "Raporlu / istirahatli"), (IZIN, "İzinli"), (GOREV, "Görevli / geçici görev"),
                (KURS, "Kurs / eğitim"), (DIGER, "Diğer")]

    veren = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="verdigi_vekaletler",
                              verbose_name="Vekâlet veren (asıl)")
    vekil = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="aldigi_vekaletler",
                              verbose_name="Vekil")
    gorev = models.CharField("Vekâlet edilen görev", max_length=120,
                             help_text="ör. Bilgisayar Teknolojisi Bölüm Başkanı, Personel Şube Müdürü")
    neden = models.CharField("Neden", max_length=6, choices=NEDENLER, default=RAPOR)
    baslangic = models.DateField("Başlangıç")
    bitis = models.DateField("Bitiş (bu gün dahil)")
    aciklama = models.CharField("Açıklama", max_length=300, blank=True)
    sonlandirma = models.DateTimeField("Erken sonlandırma", null=True, blank=True)
    sonlandiran = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-baslangic", "-pk"]
        verbose_name = "Vekâlet"
        verbose_name_plural = "Vekâletler"
        constraints = [models.CheckConstraint(condition=models.Q(bitis__gte=models.F("baslangic")),
                                              name="vekalet_aralik_gecerli")]

    def __str__(self):
        return f"{self.veren.ad_soyad} → {self.vekil.ad_soyad} ({self.gorev})"

    # durum: başlayacak / yürürlükte / sona erdi / sonlandırıldı
    BASLAYACAK, YURURLUKTE, BITTI, SONLANDIRILDI = "baslayacak", "yururlukte", "bitti", "sonlandirildi"
    DURUM_ADI = {BASLAYACAK: "Başlayacak", YURURLUKTE: "Yürürlükte", BITTI: "Sona erdi",
                 SONLANDIRILDI: "Erken sonlandırıldı"}

    def durum_kodu(self, bugun=None):
        bugun = bugun or timezone.localdate()
        if self.sonlandirma:
            return self.SONLANDIRILDI
        if bugun < self.baslangic:
            return self.BASLAYACAK
        return self.YURURLUKTE if bugun <= self.bitis else self.BITTI

    @property
    def durum(self):
        return self.durum_kodu()

    @property
    def durum_adi(self):
        return self.DURUM_ADI[self.durum]

    @property
    def gun_sayisi(self):
        return (self.bitis - self.baslangic).days + 1

    @property
    def kalan_gun(self):
        """Yürürlükteyse bitişe kalan gün (bugün dahil), başlayacaksa başlamaya kalan gün."""
        bugun = timezone.localdate()
        if self.durum == self.YURURLUKTE:
            return (self.bitis - bugun).days + 1
        if self.durum == self.BASLAYACAK:
            return (self.baslangic - bugun).days
        return None

    @property
    def aralik_metni(self):
        if self.baslangic == self.bitis:
            return f"{self.baslangic:%d.%m.%Y}"
        if self.baslangic.year == self.bitis.year:
            return f"{self.baslangic:%d.%m} – {self.bitis:%d.%m.%Y}"
        return f"{self.baslangic:%d.%m.%Y} – {self.bitis:%d.%m.%Y}"
