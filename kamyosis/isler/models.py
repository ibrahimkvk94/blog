"""İş listesi: sistem sahibinin Claude'a (yapay zekâ geliştirme yardımcısı) bıraktığı işler.

Liste yalnızca "iş listesi sahibi" izni verilmiş hesaplara açıktır (süper kullanıcılık yetmez; izin elle verilir).
Claude listeyi bir oturumda ya da zamanlanmış kontrolde `manage.py isler` komutuyla okur, işi yapar ve sonucunu
nota yazar. Riskli işler (canlıya alma, ortak depoya gönderme, veri silme, parola / yetki değişikliği …) önce "onay
bekliyor" durumuna alınır; sahibi sayfadan onaylayınca bir sonraki kontrolde tamamlanır.
"""

from django.conf import settings
from django.db import models


class Is(models.Model):
    BEKLIYOR, YAPILIYOR, ONAY, SORU, TAMAM, IPTAL = "bekliyor", "yapiliyor", "onay", "soru", "tamam", "iptal"
    DURUMLAR = [(BEKLIYOR, "Bekliyor"), (YAPILIYOR, "Yapılıyor"), (ONAY, "Onay bekliyor"), (SORU, "Soru var"),
                (TAMAM, "Tamamlandı"), (IPTAL, "İptal")]
    ACIK = (BEKLIYOR, YAPILIYOR, ONAY, SORU)
    NORMAL, ACIL, DUSUK = "normal", "acil", "dusuk"
    ONCELIKLER = [(ACIL, "Acil"), (NORMAL, "Normal"), (DUSUK, "Düşük")]

    baslik = models.CharField("Başlık", max_length=200)
    aciklama = models.TextField("Açıklama", blank=True)
    oncelik = models.CharField("Öncelik", max_length=8, choices=ONCELIKLER, default=NORMAL)
    durum = models.CharField("Durum", max_length=10, choices=DURUMLAR, default=BEKLIYOR, db_index=True)
    onaylandi = models.BooleanField("Onaylandı", default=False,
                                    help_text="Onay bekleyen iş sahibince onaylandı; Claude bir sonraki kontrolde tamamlar.")
    dis_erisim = models.BooleanField("İnternetten girildi", default=False)
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleme = models.DateTimeField(auto_now=True)
    tamamlanma = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-olusturma"]
        verbose_name = "İş"
        verbose_name_plural = "İş listesi"
        permissions = [("is_listesi", "İş listesini kullanabilir (Claude'a iş bırakır)")]

    def __str__(self):
        return f"#{self.pk} {self.baslik}"

    @property
    def acik(self):
        return self.durum in self.ACIK


class IsNotu(models.Model):
    """İşin zaman çizelgesi: sahibin ekleri / cevapları ve Claude'un notları."""

    is_kaydi = models.ForeignKey(Is, on_delete=models.CASCADE, related_name="notlar")
    claude = models.BooleanField("Claude'un notu", default=False)
    yazan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    metin = models.TextField("Not")
    durum = models.CharField("Yeni durum", max_length=10, choices=Is.DURUMLAR, blank=True)
    zaman = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["zaman", "pk"]
        verbose_name = "İş notu"
        verbose_name_plural = "İş notları"
