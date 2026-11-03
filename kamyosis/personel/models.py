from django.db import models


class Bolum(models.Model):
    ad = models.CharField("Bölüm adı", max_length=100, unique=True)
    kod = models.CharField("Kısa kod", max_length=3, unique=True, null=True, blank=True)
    ders_onekleri = models.CharField(
        "Ek ders kodu önekleri", max_length=100, blank=True,
        help_text="Kısa koddan farklı önekle başlayıp bu bölüme ait sayılacak dersler, virgülle (ör. TBE,SBE).",
    )
    aktif = models.BooleanField(default=True)
    eski_id = models.IntegerField("Access ID", unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Bölüm"
        verbose_name_plural = "Bölümler"
        ordering = ["ad"]

    def __str__(self):
        return self.ad

    @property
    def onekler(self):
        """Bu bölüme ait ders/kısım kodu önekleri (kısa kod + ek önekler)."""
        ek = [o.strip() for o in self.ders_onekleri.split(",") if o.strip()]
        return ([self.kod] if self.kod else []) + ek


class Secenek(models.Model):
    """Rütbe, sınıf ve unvan listeleri (Access: smV47Secenek)."""

    RUTBE, SINIF, UNVAN = "R", "S", "U"
    TUR_SECENEKLERI = [(RUTBE, "Rütbe"), (SINIF, "Sınıf"), (UNVAN, "Unvan")]

    tur = models.CharField("Tür", max_length=1, choices=TUR_SECENEKLERI)
    metin = models.CharField("Metin", max_length=40)
    aktif = models.BooleanField(default=True)
    one_cikan = models.BooleanField(
        "Unvan önde", default=False,
        help_text="Unvanlarda: işaretliyse künyede unvan sınıf/rütbeden önce yazılır (ör. Dr.Öğt.Üyesi Öğ.Yb.), "
                  "değilse sonra (ör. Öğ.Ütğm. Dr.). PPYS'deki “Önde”. Seçim listelerinde de önce gösterilir.",
    )
    sira = models.PositiveIntegerField("Sıra", default=0)
    eski_id = models.IntegerField("Access ID", unique=True, null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Seçenek (rütbe/sınıf/unvan)"
        verbose_name_plural = "Seçenekler (rütbe/sınıf/unvan)"
        ordering = ["tur", "-one_cikan", "sira", "metin"]

    def __str__(self):
        return self.metin


class Personel(models.Model):
    ad_soyad = models.CharField("Ad soyad", max_length=100)
    personel_kodu = models.CharField("T.C. kimlik no", max_length=30, unique=True, null=True, blank=True)
    sicil = models.CharField("Sicil no", max_length=30, blank=True)
    bolum = models.ForeignKey(
        Bolum, on_delete=models.PROTECT, null=True, blank=True, related_name="personeller", verbose_name="Bölüm",
    )
    rutbe = models.ForeignKey(
        Secenek, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        limit_choices_to={"tur": Secenek.RUTBE}, verbose_name="Rütbe",
    )
    sinif = models.ForeignKey(
        Secenek, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        limit_choices_to={"tur": Secenek.SINIF}, verbose_name="Sınıf",
    )
    unvan = models.ForeignKey(
        Secenek, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
        limit_choices_to={"tur": Secenek.UNVAN}, verbose_name="Unvan",
    )
    aktif = models.BooleanField("Aktif", default=True)

    NOBET_TUTAR, NOBET_MUAF, NOBET_TUTAMAZ = "tutar", "muaf", "tutamaz"
    NOBET_DURUMLARI = [(NOBET_TUTAR, "Nöbet tutar"), (NOBET_MUAF, "Muaf"), (NOBET_TUTAMAZ, "Tutamaz")]
    nobet_durumu = models.CharField("Nöbet durumu", max_length=8, choices=NOBET_DURUMLARI, default=NOBET_TUTAR)
    nobet_muafiyet_nedeni = models.CharField(
        "Muafiyet nedeni", max_length=60, blank=True, help_text="ör. YDGG, YİGG, Geçici süre ile muaf",
    )
    nobet_muafiyet_bitis = models.DateField(
        "Muafiyet bitişi", null=True, blank=True,
        help_text="Geçici muafiyetlerde: bu tarihten sonra başlayan aylarda personel yeniden nöbete yazılır.",
    )

    eski_id = models.IntegerField("Access ID", unique=True, null=True, blank=True, editable=False)
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Personel"
        verbose_name_plural = "Personel"
        ordering = ["ad_soyad"]

    def __str__(self):
        return self.tam_ad

    @property
    def kunye(self):
        """PPYS kuralı (V47Birlestir): unvan "önde" ise Unvan + SınıfRütbe, değilse SınıfRütbe + Unvan.
        Sınıf kısaltmayla (nokta) bitiyorsa rütbeye bitişik, değilse boşlukla yazılır:
        "Dr.Öğt.Üyesi Öğ.Yb.", "Öğ.Ütğm. Dr.", "Topçu Atğm.", "Öğt.Gör.".
        Tüm ekranlarda, çıktılarda ve Ders Programı modülünde bu kullanılır."""
        sinif, rutbe = str(self.sinif or ""), str(self.rutbe or "")
        ayirac = " " if sinif and rutbe and not sinif.endswith(".") else ""
        sinif_rutbe = f"{sinif}{ayirac}{rutbe}"
        unvan = str(self.unvan or "")
        parcalar = [unvan, sinif_rutbe] if self.unvan and self.unvan.one_cikan else [sinif_rutbe, unvan]
        return " ".join(p for p in parcalar if p)

    @property
    def tam_ad(self):
        """Künye + ad soyad, ör. "Öğ.Ütğm. Ali KAYA", "Dr.Öğt.Üyesi Öğ.Yb. Ayşe YILMAZ"."""
        return " ".join(p for p in (self.kunye, self.ad_soyad) if p)
