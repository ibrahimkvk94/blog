from django.db import models

from kimlik.models import KimlikBilgileri


class Ogrenci(KimlikBilgileri):
    """Öğrenci kütüğü (Öğrenci Kaydı). Kimlik bilgileri kimlik kartından okunarak ya da elle girilir.

    Ders Programı modülündeki öğrenci (timetable.Student) ayrıdır; ileride numara ile bağlanabilir."""

    numara = models.CharField("Öğrenci no", max_length=30, blank=True)
    sinif = models.CharField("Sınıf / şube", max_length=40, blank=True)
    bolum = models.ForeignKey("personel.Bolum", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="ogrenciler", verbose_name="Bölüm")
    aktif = models.BooleanField("Aktif", default=True)
    olusturma = models.DateTimeField(auto_now_add=True)
    guncelleme = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Öğrenci"
        verbose_name_plural = "Öğrenciler"
        ordering = ["soyad", "ad"]
        constraints = [models.UniqueConstraint(fields=["tc"], condition=~models.Q(tc=""),
                                               name="ogrenci_tc_tekil")]

    def __str__(self):
        return self.ad_soyad
