"""Personel yoklaması.

Yalnızca istisnalar kaydedilir: herkes varsayılan olarak "mevcut" sayılır; izin, rapor, görev gibi durumlar tarih-saat
aralığıyla girilir (YoklamaKaydi). Günün yoklaması bu kayıtlardan hesaplanır. Bölüm, günün yoklamasını kontrol edip
"verdim" der (GunlukOnay); onaydan sonra o güne dokunan değişiklik onay kaydında işaretlenir.

Tam gün kaydı başlangıç günü 00:00'dan bitiş gününün ertesi 00:00'a kadardır; saatlik kayıt aynı gün içinde iki saat
arasıdır. Aynı personelin kayıtları çakışamaz.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from personel.models import Bolum, Personel

RENKLER = [
    ("#2f5d8a", "Lacivert"), ("#0e7490", "Camgöbeği"), ("#15803d", "Yeşil"), ("#b45309", "Turuncu"),
    ("#b91c1c", "Kırmızı"), ("#7c3aed", "Mor"), ("#be185d", "Pembe"), ("#475569", "Gri"), ("#a16207", "Hardal"),
]


class IzinTuru(models.Model):
    """İzin / durum türü (yıllık izin, raporlu, görevli …). İdari işler yetkilisi ekler, düzenler, kaldırır."""

    ad = models.CharField("Ad", max_length=60, unique=True)
    kisa = models.CharField("Kısaltma", max_length=6, help_text="Takvim hücrelerinde görünür, ör. Yİ, RP, GRV.")
    renk = models.CharField("Renk", max_length=7, choices=RENKLER, default="#2f5d8a")
    sira = models.PositiveSmallIntegerField("Sıra", default=10)
    aktif = models.BooleanField("Kullanımda", default=True, help_text="Kapalı tür yeni kayıtta seçilemez; eski kayıtlar korunur.")
    aciklama = models.CharField("Açıklama", max_length=200, blank=True)
    yillik_hak = models.PositiveSmallIntegerField(
        "Yıllık hak (gün)", null=True, blank=True,
        help_text="Boş: sınırsız. Takvim yılı (1 Ocak'ta yenilenir), takvim günü; yalnızca tam gün kayıtları düşer.")
    mevcut_sayilir = models.BooleanField(
        "Bilgi amaçlı (mevcut sayılır)", default=False,
        help_text="ör. Garnizon terk: personel kartında görünür; günlük yoklamada, formda ve raporda yok sayılmaz.")
    rapor_sirasi = models.PositiveSmallIntegerField(
        "Rapor sırası", null=True, blank=True,
        help_text="Yoklama formunda gayri mevcutlar bu sıraya göre listelenir (1 en başta); sırasızlar sonda.")

    class Meta:
        ordering = ["sira", "ad"]
        verbose_name = "İzin türü"
        verbose_name_plural = "İzin türleri"

    def __str__(self):
        return self.ad


class YoklamaKaydi(models.Model):
    personel = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="yoklama_kayitlari")
    tur = models.ForeignKey(IzinTuru, on_delete=models.PROTECT, related_name="kayitlar", verbose_name="Tür")
    baslangic = models.DateTimeField("Başlangıç", db_index=True)
    bitis = models.DateTimeField("Bitiş", db_index=True)
    aciklama = models.CharField("Açıklama", max_length=300, blank=True)
    olusturan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)
    surum = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["-baslangic"]
        verbose_name = "Yoklama kaydı"
        verbose_name_plural = "Yoklama kayıtları"
        indexes = [models.Index(fields=["personel", "baslangic", "bitis"])]
        constraints = [models.CheckConstraint(condition=models.Q(bitis__gt=models.F("baslangic")), name="yoklama_aralik_gecerli")]

    def __str__(self):
        return f"{self.personel.ad_soyad} · {self.tur} · {self.aralik_metni}"

    @property
    def yerel_bas(self):
        return timezone.localtime(self.baslangic)

    @property
    def yerel_bit(self):
        return timezone.localtime(self.bitis)

    @property
    def tam_gun(self):
        b, s = self.yerel_bas, self.yerel_bit
        return b.hour == b.minute == 0 and s.hour == s.minute == 0

    @property
    def gun_sayisi(self):
        return (self.yerel_bit.date() - self.yerel_bas.date()).days if self.tam_gun else 0

    @property
    def son_gun(self):
        """Tam gün kaydının son günü (bitiş ertesi gün 00:00 olduğu için bir gün geri)."""
        import datetime

        return self.yerel_bit.date() - datetime.timedelta(days=1) if self.tam_gun else self.yerel_bit.date()

    @property
    def aralik_metni(self):
        b, s = self.yerel_bas, self.yerel_bit
        if self.tam_gun:
            if self.gun_sayisi == 1:
                return f"{b:%d.%m.%Y} (tam gün)"
            return f"{b:%d.%m.%Y} – {self.son_gun:%d.%m.%Y} ({self.gun_sayisi} gün)"
        if b.date() == s.date():
            return f"{b:%d.%m.%Y} {b:%H:%M}–{s:%H:%M}"
        return f"{b:%d.%m.%Y %H:%M} – {s:%d.%m.%Y %H:%M}"


class YoklamaGecmisi(models.Model):
    """Her ekleme, düzenleme ve silme (kim, ne zaman, ne yaptı; kaydın o anki hâli)."""

    EKLE, DUZENLE, SIL = "ekle", "duzenle", "sil"
    ISLEMLER = [(EKLE, "Eklendi"), (DUZENLE, "Düzenlendi"), (SIL, "Silindi")]

    personel = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="yoklama_gecmisi")
    kayit_id = models.PositiveBigIntegerField(null=True)
    islem = models.CharField(max_length=8, choices=ISLEMLER)
    ozet = models.CharField(max_length=400)
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now_add=True)
    onay_sonrasi = models.BooleanField(default=False, help_text="Yoklaması verilmiş bir güne dokundu.")

    class Meta:
        ordering = ["-zaman", "-id"]
        verbose_name = "Yoklama geçmişi"
        verbose_name_plural = "Yoklama geçmişi"


class GunlukOnay(models.Model):
    """Bir teşkilat biriminin (bölüm, şube müdürlüğü, kısım …) bir günün yoklamasını kesinleştirmesi."""

    birim = models.ForeignKey("personel.TeskilatBirimi", on_delete=models.CASCADE, related_name="yoklama_onaylari")
    tarih = models.DateField(db_index=True)
    onaylayan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now_add=True)
    degisti = models.DateTimeField("Onaydan sonra değişti", null=True, blank=True)

    class Meta:
        ordering = ["-tarih"]
        verbose_name = "Günlük yoklama onayı"
        verbose_name_plural = "Günlük yoklama onayları"
        constraints = [models.UniqueConstraint(fields=["birim", "tarih"], name="yoklama_onay_birim_tekil")]

    def __str__(self):
        return f"{self.birim} · {self.tarih:%d.%m.%Y}"


class PersonelGrubu(models.Model):
    """Günlük yoklama formundaki sütun (ve "Görevi") için elle atama. Kayıt yoksa grup künyeden otomatik bulunur."""

    GENERAL, OE_SIVIL, OE_SUBAY, OE_ASTSUBAY, SUBAY, ASTSUBAY, SIVIL_MEMUR = (
        "general", "oe_sivil", "oe_subay", "oe_astsubay", "subay", "astsubay", "sivil_memur")
    GRUPLAR = [
        (GENERAL, "General / Amiral"),
        (OE_SIVIL, "Öğretim elemanı (sivil)"),
        (OE_SUBAY, "Öğretim elemanı (subay)"),
        (OE_ASTSUBAY, "Öğretim elemanı (astsubay)"),
        (SUBAY, "Subay (Yd.Sb. dahil)"),
        (ASTSUBAY, "Astsubay (Yd.Asb. dahil)"),
        (SIVIL_MEMUR, "Sivil memur"),
    ]

    personel = models.OneToOneField(Personel, on_delete=models.CASCADE, related_name="yoklama_grubu")
    grup = models.CharField("Yoklama grubu", max_length=12, choices=GRUPLAR, blank=True,
                            help_text="Boş: künyeden otomatik.")
    gorev = models.CharField("Görevi", max_length=80, blank=True, help_text="Boş: otomatik (ör. Öğretim Elemanı (BSB)).")

    class Meta:
        verbose_name = "Yoklama grubu"
        verbose_name_plural = "Yoklama grupları"

    def __str__(self):
        return f"{self.personel.ad_soyad} · {self.get_grup_display() or 'otomatik'}"
