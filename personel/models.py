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
    baskan = models.ForeignKey(
        "Personel", on_delete=models.SET_NULL, null=True, blank=True, related_name="baskani_oldugu_bolumler",
        verbose_name="Bölüm başkanı",
    )

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


OGRETIM_UYESI_UNVANLARI = {"Prof.Dr.", "Doç.Dr.", "Dr.Öğt.Üyesi"}
AKADEMIK_UNVANLAR = OGRETIM_UYESI_UNVANLARI | {"Öğt.Gör.", "Öğt.Gör.Dr.", "Dr.", "Arş.Gör.", "Okt.", "Uzm."}
MEMUR_UNVANLARI = {"De.Me.", "Söz.De.Me.", "VHKİ"}


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
    fotograf = models.ImageField(
        "Fotoğraf", upload_to="personel/", blank=True, editable=False,
        help_text="Personel yoklaması kartında gösterilir; yüklenirken 600 piksele küçültülür (yoklama/foto.py).")
    # Sınav görevi rolleri (PPYS SPS spRol): A salon amiri, G gözetmen, T taşıyıcı; boş = sınav görevi verilmez
    SINAV_ROLLERI = [("A", "Salon amiri"), ("G", "Gözetmen"), ("T", "Taşıyıcı")]
    sinav_rolleri = models.CharField(
        "Sınav görev rolleri", max_length=3, default="GT", blank=True,
        help_text="A = salon amiri, G = gözetmen, T = taşıyıcı (ör. AG). Boş = sınav görevi verilmez.",
    )

    # Personel kartı (yönetici): ders / sınav kullanımı, teşkilattaki yeri, idari kadro
    derse_girebilir = models.BooleanField(
        "Derse girebilir", default=True,
        help_text="İşaretsizse ders mazereti, ders takibi ve program eşleştirme listelerinde çıkmaz.")
    sinav_gorevi_alabilir = models.BooleanField(
        "Sınav görevi alabilir", default=True,
        help_text="İşaretsizse sınav görevlendirmesine (salon amiri, gözetmen, taşıyıcı) alınmaz.")
    teskilat_birimi = models.ForeignKey(
        "TeskilatBirimi", on_delete=models.SET_NULL, null=True, blank=True, related_name="personeller",
        verbose_name="Teşkilattaki birimi", help_text="Boşsa bölümüne göre (bölüm başkanlığı) sayılır.")
    gorev_unvani = models.CharField("Görev unvanı", max_length=80, blank=True,
                                    help_text="ör. Şube Müdürü, Kısım Amiri, Müdür Yardımcısı")
    idari_kadro = models.BooleanField("İdari kadro", default=False)
    gelistirici = models.BooleanField("Geliştirici", default=False,
                                      help_text="KAMYOSİS'i geliştirenler: kartta neon geliştirici nişanı.")
    brans = models.CharField("Branş", max_length=60, blank=True,
                             help_text="Öğretim elemanının alanı, ör. Fizik, Matematik, Elektronik. Görev unvanı yoksa "
                                       "raporlarda “Fizik Öğretim Görevlisi” gibi yazılır.")

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

    def kadro_gorevi_metni(self, ogretim=None):
        """Raporlardaki "Görevi": görev unvanı (ör. Ders Plan Subayı, Yüksekokul Müdürü) varsa o; yoksa De.Me., VHKİ
        gibi memur unvanı; yoksa öğretim elemanında branşla "Fizik Öğretim Görevlisi" / "… Öğretim Üyesi".
        ogretim verilmezse künyeden (bölüm, Öğ. sınıfı, akademik unvan) anlaşılır. Bulunamazsa boş."""
        if self.gorev_unvani:
            return self.gorev_unvani
        unvan = str(self.unvan or "").strip()
        if unvan in MEMUR_UNVANLARI:
            return unvan
        if ogretim is None:
            ogretim = bool(self.bolum_id) or str(self.sinif or "").strip() == "Öğ." or unvan in AKADEMIK_UNVANLAR
        if ogretim and self.brans:
            return f"{self.brans} {'Öğretim Üyesi' if unvan in OGRETIM_UYESI_UNVANLARI else 'Öğretim Görevlisi'}"
        return ""

    @property
    def kadro_gorevi(self):
        return self.kadro_gorevi_metni()

    @property
    def tam_ad(self):
        """Künye + ad soyad, ör. "Öğ.Ütğm. Ali KAYA", "Dr.Öğt.Üyesi Öğ.Yb. Ayşe YILMAZ"."""
        return " ".join(p for p in (self.kunye, self.ad_soyad) if p)


class TeskilatBirimi(models.Model):
    """Okulun teşkilat şeması (müdürlük, müdür yardımcılığı, sekreterlik, şube müdürlüğü, kısım, koordinatörlük,
    bölüm başkanlığı). Menü/yetki ağacından (core.Birim) ayrıdır: personelin nerede görev yaptığını gösterir."""

    MUDURLUK, YARDIMCI, SEKRETERLIK, SUBE, KISIM, KOORDINATORLUK, BASKANLIKLAR, BOLUM = (
        "mudurluk", "yardimci", "sekreterlik", "sube", "kisim", "koordinatorluk", "baskanliklar", "bolum")
    TURLER = [(MUDURLUK, "Müdürlük"), (YARDIMCI, "Müdür yardımcılığı"), (SEKRETERLIK, "Sekreterlik"),
              (SUBE, "Şube müdürlüğü"), (KISIM, "Kısım"), (KOORDINATORLUK, "Koordinatörlük"),
              (BASKANLIKLAR, "Bölüm başkanlıkları"), (BOLUM, "Bölüm başkanlığı")]

    ad = models.CharField("Ad", max_length=120)
    ust = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="altlar",
                            verbose_name="Üst birim")
    tur = models.CharField("Tür", max_length=16, choices=TURLER, default=KISIM)
    bolum = models.OneToOneField(Bolum, on_delete=models.SET_NULL, null=True, blank=True, related_name="teskilat",
                                 verbose_name="Akademik bölüm", help_text="Bölüm başkanlığıysa bağlı bölüm.")
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Aktif", default=True)

    class Meta:
        verbose_name = "Teşkilat birimi"
        verbose_name_plural = "Teşkilat şeması"
        ordering = ["sira", "ad"]

    def __str__(self):
        return self.ad


class KartAlani(models.Model):
    """Personel kartındaki ek bilgi alanları (yöneticiler ekler / kaldırır): telefon, adres, kan grubu …"""

    METIN, UZUN, TARIH, SAYI, TELEFON, EPOSTA, SECIM = "metin", "uzun", "tarih", "sayi", "telefon", "eposta", "secim"
    TURLER = [(METIN, "Kısa metin"), (UZUN, "Uzun metin"), (TARIH, "Tarih"), (SAYI, "Sayı"), (TELEFON, "Telefon"),
              (EPOSTA, "E-posta"), (SECIM, "Seçim listesi")]

    ad = models.CharField("Alan adı", max_length=60, unique=True)
    grup = models.CharField("Bölüm (kart başlığı)", max_length=40, default="İletişim",
                            help_text="Kartta hangi başlık altında görüneceği, ör. İletişim, Kimlik, Sağlık.")
    tur = models.CharField("Tür", max_length=10, choices=TURLER, default=METIN)
    secenekler = models.CharField("Seçenekler", max_length=300, blank=True,
                                  help_text="Seçim listesi için virgülle ayırın, ör. 0 Rh+, A Rh+")
    sira = models.PositiveIntegerField("Sıra", default=0)
    aktif = models.BooleanField("Kullanımda", default=True)
    onemli = models.BooleanField("Boşsa eksik sayılır", default=False,
                                 help_text="İşaretliyse bu alan boş olan kartlar \"eksik\" uyarısı alır.")

    class Meta:
        verbose_name = "Kart alanı"
        verbose_name_plural = "Kart alanları"
        ordering = ["grup", "sira", "ad"]

    def __str__(self):
        return self.ad

    @property
    def secenek_listesi(self):
        return [x.strip() for x in self.secenekler.split(",") if x.strip()]


class KartDegeri(models.Model):
    personel = models.ForeignKey(Personel, on_delete=models.CASCADE, related_name="kart_degerleri")
    alan = models.ForeignKey(KartAlani, on_delete=models.CASCADE, related_name="degerler")
    deger = models.TextField("Değer", blank=True)
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kart değeri"
        verbose_name_plural = "Kart değerleri"
        constraints = [models.UniqueConstraint(fields=["personel", "alan"], name="kart_degeri_tekil")]
