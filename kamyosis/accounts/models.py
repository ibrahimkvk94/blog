from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    bolum = models.ForeignKey(
        "personel.Bolum", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="kullanicilar", verbose_name="Bölüm",
    )
    teskilat_birimi = models.ForeignKey(
        "personel.TeskilatBirimi", on_delete=models.SET_NULL, null=True, blank=True, related_name="kullanicilar",
        verbose_name="Teşkilat birimi",
        help_text="Şube müdürlüğü, kısım vb. hesabıysa birimi. Doluysa bölüm yerine bu birim ve alt birimleri görülür.",
    )
    personel = models.OneToOneField(
        "personel.Personel", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="kullanici", verbose_name="Bağlı personel",
    )
    parola_degismeli = models.BooleanField(
        "İlk girişte parola değiştirmeli", default=False,
        help_text="İşaretliyse kullanıcı giriş yaptığında önce parolasını değiştirmek zorundadır.",
    )

    class Meta:
        verbose_name = "Kullanıcı"
        verbose_name_plural = "Kullanıcılar"

    def __str__(self):
        return self.get_full_name() or self.username


class IkiAdimliDogrulama(models.Model):
    """Kullanıcının iki adımlı doğrulama (authenticator uygulaması) ayarı. Kayıt yoksa ya da etkin değilse girişte
    yalnızca parola sorulur."""

    kullanici = models.OneToOneField(User, on_delete=models.CASCADE, related_name="iki_adim")
    gizli = models.CharField(max_length=64, editable=False)
    etkin = models.BooleanField("Etkin", default=False)
    son_adim = models.BigIntegerField(null=True, blank=True, editable=False,
                                      help_text="Son kabul edilen kodun zaman adımı (aynı kod ikinci kez kullanılamaz).")
    yedek_kodlar = models.JSONField(default=list, blank=True, editable=False)
    acilis = models.DateTimeField("Açılış", null=True, blank=True)
    son_kullanim = models.DateTimeField("Son kullanım", null=True, blank=True)

    class Meta:
        verbose_name = "İki adımlı doğrulama"
        verbose_name_plural = "İki adımlı doğrulama"

    def __str__(self):
        return f"{self.kullanici} · {'açık' if self.etkin else 'kapalı'}"

    @property
    def kalan_yedek(self):
        return len(self.yedek_kodlar or [])


class GuvenlikAyari(models.Model):
    """Tek satırlık giriş güvenliği ayarları (Yönetim Paneli → Güvenlik ayarları)."""

    dis_erisimde_iki_adim_zorunlu = models.BooleanField(
        "İnternetten girişte iki adımlı doğrulama zorunlu", default=True,
        help_text="Açıksa internet adresinden (Tailscale Funnel) yalnızca iki adımlı doğrulaması açık kullanıcılar "
                  "girebilir. Kurum ağından giriş etkilenmez.")
    giris_deneme_siniri = models.PositiveSmallIntegerField(
        "Hatalı giriş sınırı", default=5, help_text="Aynı kullanıcı adıyla bu kadar hatalı denemeden sonra kilit.")
    kilit_suresi_dk = models.PositiveSmallIntegerField(
        "İlk kilit süresi (dakika)", default=1, help_text="Sınır her aşıldığında kilit katsayı kadar uzar: 1, 3, 9 … dk.")
    kilit_katsayisi = models.PositiveSmallIntegerField("Kilit artış katsayısı", default=3)

    class Meta:
        verbose_name = "Güvenlik ayarları"
        verbose_name_plural = "Güvenlik ayarları"

    def __str__(self):
        return "Güvenlik ayarları"

    @classmethod
    def al(cls):
        return cls.objects.first() or cls.objects.create()
