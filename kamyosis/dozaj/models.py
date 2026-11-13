"""Dozajmatik: öğretim programları ve kısım sayılarından branş başına haftalık ders saati, öğretim elemanı mevcudu,
ders yükü ortalaması ve öğretim elemanı ihtiyacı (Plan Program Kısmı'nın Excel tablosunun yerine).

Her şey bir plan yılına (ör. 2026-2027) bağlıdır; yeni yıl öncekinden kopyalanır."""

from django.conf import settings
from django.db import models


class Yil(models.Model):
    ad = models.CharField("Eğitim-öğretim yılı", max_length=20, unique=True, help_text="ör. 2026-2027")
    varsayilan = models.BooleanField("Açılışta gösterilen", default=False)
    uyari_esigi = models.PositiveSmallIntegerField(
        "Uyarı eşiği (saat)", default=19, help_text="Ortalama ders yükü bu değere ulaşan branşlar kırmızı gösterilir.")
    ihtiyac_saat1 = models.PositiveSmallIntegerField("1. ihtiyaç hesabı (saat)", default=20)
    ihtiyac_saat2 = models.PositiveSmallIntegerField("2. ihtiyaç hesabı (saat)", default=15)
    baskan_saati = models.PositiveSmallIntegerField(
        "Bölüm başkanının ders saati", default=5,
        help_text="Bölüm başkanı bu kadar saat derse girer, kalanı diğerleri paylaşır.")
    aciklama = models.TextField("Açıklama", blank=True)
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plan yılı"
        verbose_name_plural = "Plan yılları"
        ordering = ["-ad"]

    def __str__(self):
        return self.ad


class Brans(models.Model):
    ad = models.CharField("Branş", max_length=40, unique=True)
    grup = models.CharField("Bölüm (tablodaki grup)", max_length=60, blank=True,
                            help_text="Tabloda branşların altında toplandığı başlık, ör. Beşeri ve Sosyal Bilimler.")
    sira = models.PositiveIntegerField("Sıra", default=0)
    hesapta = models.BooleanField("Tabloda hesaba katılır", default=True,
                                  help_text="Kapalıysa bu branşın saatleri tabloya girmez, ayrıca gösterilir (ör. Afet).")

    class Meta:
        verbose_name = "Branş"
        verbose_name_plural = "Branşlar"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad


class Program(models.Model):
    yil = models.ForeignKey(Yil, on_delete=models.CASCADE, related_name="programlar")
    kod = models.CharField("Kısa kod", max_length=10, help_text="ör. BİL")
    ad = models.CharField("Program adı", max_length=100)
    kisim1 = models.PositiveSmallIntegerField("1. sınıf kısım sayısı", default=0)
    kisim2 = models.PositiveSmallIntegerField("2. sınıf kısım sayısı", default=0)
    hazirlik = models.BooleanField("Hazırlık programı", default=False,
                                   help_text="Kısımları 1. ve 2. sınıf toplamına girmez, ayrıca gösterilir.")
    sira = models.PositiveIntegerField("Sıra", default=0)

    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programlar"
        ordering = ["sira", "ad"]
        constraints = [models.UniqueConstraint(fields=["yil", "kod"], name="dozaj_program_tekil")]

    def __str__(self):
        return self.ad

    def kisim(self, sinif):
        return self.kisim1 if sinif == 1 else self.kisim2


class Ders(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="dersler")
    yariyil = models.PositiveSmallIntegerField("Yarıyıl", choices=[(i, f"{i}. yarıyıl") for i in range(1, 5)])
    kod = models.CharField("Ders kodu", max_length=20)
    ad = models.CharField("Ders adı", max_length=200)
    ds = models.PositiveSmallIntegerField("Haftalık saat (DS)", default=0)
    t = models.PositiveSmallIntegerField("Teorik", default=0)
    u = models.PositiveSmallIntegerField("Uygulama", default=0)
    l = models.PositiveSmallIntegerField("Laboratuvar", default=0)
    kr = models.PositiveSmallIntegerField("Kredi", default=0)
    akts = models.PositiveSmallIntegerField("AKTS", default=0)
    ikinci_eleman = models.BooleanField(
        "Uygulamaya 2. eleman girer", default=False,
        help_text="Dersin saati değişmez; uygulama saati öğretim elemanı yüküne bir kez daha eklenir.")
    guz_kisim = models.PositiveSmallIntegerField("Güz'de alan kısım", null=True, blank=True)
    bahar_kisim = models.PositiveSmallIntegerField("Bahar'da alan kısım", null=True, blank=True)
    sira = models.PositiveIntegerField("Sıra", default=0)

    class Meta:
        verbose_name = "Ders"
        verbose_name_plural = "Dersler"
        ordering = ["program", "yariyil", "sira", "pk"]

    def __str__(self):
        return f"{self.kod} {self.ad}"

    @property
    def sinif(self):
        return 1 if self.yariyil <= 2 else 2

    @property
    def yuk(self):
        """Öğretim elemanı yükü (bir kısım için): saat + 2. eleman girerse uygulama saati."""
        return self.ds + (self.u if self.ikinci_eleman else 0)

    @property
    def dagilim_ozel(self):
        return self.guz_kisim is not None or self.bahar_kisim is not None

    def kisimlar(self):
        """(Güz'de alan kısım, Bahar'da alan kısım). Ayarlanmamışsa yarıyıla göre: tek yarıyıl Güz, çift Bahar."""
        if self.dagilim_ozel:
            return self.guz_kisim or 0, self.bahar_kisim or 0
        n = self.program.kisim(self.sinif)
        return (n, 0) if self.yariyil % 2 else (0, n)


class KodBransi(models.Model):
    """Bir ders kodunu hangi branş verir (o yıl bütün programlarda aynı)."""

    yil = models.ForeignKey(Yil, on_delete=models.CASCADE, related_name="kod_branslari")
    kod = models.CharField("Ders kodu", max_length=20)
    brans = models.ForeignKey(Brans, on_delete=models.CASCADE, related_name="kodlar")

    class Meta:
        verbose_name = "Ders kodu branşı"
        verbose_name_plural = "Ders kodu branşları"
        constraints = [models.UniqueConstraint(fields=["yil", "kod"], name="dozaj_kod_bransi_tekil")]


class BransAyari(models.Model):
    """Branşın o yılki elle girilen bilgileri: karargâh ve okul dışından gelenler, yedek subay sayımı."""

    DESTEK_GUZ, DESTEK_BAHAR, DESTEK_IKISI = "1", "2", "12"
    DESTEKLER = [(DESTEK_IKISI, "Güz ve Bahar"), (DESTEK_GUZ, "Yalnız Güz"), (DESTEK_BAHAR, "Yalnız Bahar")]

    yil = models.ForeignKey(Yil, on_delete=models.CASCADE, related_name="brans_ayarlari")
    brans = models.ForeignKey(Brans, on_delete=models.CASCADE, related_name="ayarlar")
    atgm_dahil = models.BooleanField("Yedek subaylar toplama dahil", default=True)
    kh_sayi = models.PositiveSmallIntegerField("Karargâhtan gelen (kişi)", default=0,
                                               help_text="Personel listesinde \"Kh.\" işaretlenenlere eklenir.")
    dis_sayi = models.PositiveSmallIntegerField("Okul dışından gelen (kişi)", default=0,
                                                help_text="Personel listesinde \"Okul dışı\" işaretlenenlere eklenir.")
    dis_saat = models.PositiveSmallIntegerField("Karargâh ve okul dışından gelenlerin haftalık saati", default=0)
    destek = models.CharField("Destek verdikleri dönem", max_length=2, choices=DESTEKLER, default=DESTEK_IKISI)

    class Meta:
        verbose_name = "Branş ayarı"
        verbose_name_plural = "Branş ayarları"
        constraints = [models.UniqueConstraint(fields=["yil", "brans"], name="dozaj_brans_ayari_tekil")]


class KisiAyari(models.Model):
    """Bir personelin o yılki branşı ve (gerekirse) kadro sınıfı. Kayıt yoksa kart bilgisinden önerilir."""

    BB, SB, ASB, SIVIL, YEDEK, KH, DIS, HARIC = "bb", "sb", "asb", "sivil", "yedek", "kh", "dis", "haric"
    KADROLAR = [(BB, "Bölüm başkanı"), (SB, "Subay"), (ASB, "Astsubay"), (SIVIL, "Sivil"), (YEDEK, "Yedek subay"),
                (KH, "Karargâhtan (Kh.)"), (DIS, "Okul dışından"), (HARIC, "Mevcuda dahil değil")]

    yil = models.ForeignKey(Yil, on_delete=models.CASCADE, related_name="kisi_ayarlari")
    personel = models.ForeignKey("personel.Personel", on_delete=models.CASCADE, related_name="dozaj_ayarlari")
    brans = models.ForeignKey(Brans, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    brans_yok = models.BooleanField("Derse girmiyor", default=False,
                                    help_text="İşaretliyse önerilen branş kullanılmaz; bu kişi hesaba girmez.")
    kadro = models.CharField("Kadro", max_length=6, choices=KADROLAR, blank=True)
    guncelleyen = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kişi ayarı"
        verbose_name_plural = "Kişi ayarları"
        constraints = [models.UniqueConstraint(fields=["yil", "personel"], name="dozaj_kisi_ayari_tekil")]
