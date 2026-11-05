from django.conf import settings
from django.db import models

from .okuma import tc_gecerli


class KimlikBilgileri(models.Model):
    """T.C. kimlik kartındaki bilgiler (kimlik okuma listesi ve öğrenci kaydı ortak kullanır)."""

    CINSIYETLER = [("E", "Erkek"), ("K", "Kadın")]

    tc = models.CharField("T.C. kimlik no", max_length=11, blank=True)
    soyad = models.CharField("Soyadı", max_length=60, blank=True)
    ad = models.CharField("Adı", max_length=60, blank=True)
    dogum_tarihi = models.DateField("Doğum tarihi", null=True, blank=True)
    cinsiyet = models.CharField("Cinsiyeti", max_length=1, choices=CINSIYETLER, blank=True)
    seri_no = models.CharField("Seri no", max_length=12, blank=True)
    uyruk = models.CharField("Uyruğu", max_length=20, blank=True)
    son_gecerlilik = models.DateField("Son geçerlilik", null=True, blank=True)
    anne_adi = models.CharField("Anne adı", max_length=60, blank=True)
    baba_adi = models.CharField("Baba adı", max_length=60, blank=True)
    veren_makam = models.CharField("Veren makam", max_length=80, blank=True)

    class Meta:
        abstract = True

    @property
    def ad_soyad(self):
        """KAMYOSİS biçimi: "Ali KAYA"."""
        from .okuma import tr_baslik, tr_buyuk

        return " ".join(p for p in (tr_baslik(self.ad), tr_buyuk(self.soyad)) if p)

    @property
    def tc_dogru(self):
        return tc_gecerli(self.tc)


class KimlikKaydi(KimlikBilgileri):
    """Kimlik kartından okunan, henüz aktarılmamış satır (çalışma listesi). Fotoğraf saklanmaz."""

    PERSONEL, OGRENCI = "personel", "ogrenci"
    TURLER = [(PERSONEL, "Personel"), (OGRENCI, "Öğrenci")]

    tur = models.CharField("Tür", max_length=8, choices=TURLER, blank=True)
    uyarilar = models.TextField("Uyarılar", blank=True)
    supheli = models.CharField("Kontrol edilecek alanlar", max_length=200, blank=True)
    kaynak = models.CharField("Kaynak", max_length=10, default="kart", editable=False)  # kart / excel
    ekleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", editable=False)
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleme = models.DateTimeField(auto_now=True)
    aktarim = models.DateTimeField("Aktarıldı", null=True, blank=True, editable=False)
    aktarim_notu = models.CharField("Aktarım", max_length=200, blank=True, editable=False)

    class Meta:
        verbose_name = "Kimlik okuma kaydı"
        verbose_name_plural = "Kimlik okuma kayıtları"
        ordering = ["-olusturma", "-id"]

    def __str__(self):
        return self.ad_soyad or f"Kayıt {self.pk}"

    @property
    def supheli_alanlar(self):
        return {a for a in self.supheli.split(",") if a}

    @property
    def uyari_listesi(self):
        return [u for u in self.uyarilar.splitlines() if u.strip()]
