from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    bolum = models.ForeignKey(
        "personel.Bolum", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="kullanicilar", verbose_name="Bölüm",
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
