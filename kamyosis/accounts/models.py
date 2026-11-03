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
