"""Mazeret bildirimleri (PPYS DMS ve SMS karşılığı).

Ders mazereti: personelin dönem boyunca her hafta geçerli gün × ders saati şablonu.
Sınav mazereti: Sınav Planlama'daki bir sınav döneminin her günü × oturumu (ör. "2026-11-10 09:30").
Hücre değerleri Program Hazırlama modülüyle aynıdır: kayıt yok = uygun (✓),
"no" = ders/görev verilemez (✗), "maybe" = mümkünse verilmesin (?).
Bildirim kaydının olması "bildirildi" demektir; boş şablon = "mazereti yok".

Her dönem izgara() ile ekranda gösterilecek ızgarayı, anahtarlar() ile geçerli hücre anahtarlarını verir.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from personel.models import Personel

YASAK, KOSULLU = "no", "maybe"
DURUMLAR = (YASAK, KOSULLU)
GUN_ADLARI = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


class DersMazeretDonemi(models.Model):
    ad = models.CharField("Ad", max_length=80, help_text="ör. 2026-2027 Bahar")
    gun_sayisi = models.PositiveSmallIntegerField("Gün sayısı", default=5, help_text="5 = Pazartesi–Cuma")
    saat_sayisi = models.PositiveSmallIntegerField("Ders saati sayısı", default=8)
    giris_acik = models.BooleanField("Bildirime açık", default=True)
    son_bildirim = models.DateTimeField(
        "Son bildirim zamanı", null=True, blank=True,
        help_text="Bu zamandan sonra bölümler değişiklik yapamaz (yöneticiler yapabilir). Boş = süresiz.",
    )
    okul = models.ForeignKey(
        "timetable.School", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="Program Hazırlama'daki program",
        help_text="Seçilirse her bildirim bu programdaki öğretmenin müsaitliğine yazılır.",
    )
    aciklama = models.TextField("Bölümlere not", blank=True)
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ders mazeret dönemi"
        verbose_name_plural = "Ders mazeret dönemleri"
        ordering = ["-olusturma"]

    def __str__(self):
        return self.ad

    @property
    def acik_mi(self):
        return self.giris_acik and (self.son_bildirim is None or timezone.now() <= self.son_bildirim)

    @property
    def gunler(self):
        return GUN_ADLARI[: self.gun_sayisi]

    def izgara(self):
        """(sütun başlıkları, [(satır başlığı, [(anahtar, açıklama), ...]), ...])."""
        # Saat aralığı yazılmaz: Cuma öğle arası farklı olduğu için yanıltıcı olur.
        sutunlar = [f"{s}. saat" for s in range(1, self.saat_sayisi + 1)]
        satirlar = [(gun, [(f"{g}-{s}", f"{gun} {s + 1}. saat") for s in range(self.saat_sayisi)])
                    for g, gun in enumerate(self.gunler)]
        return sutunlar, satirlar

    def anahtarlar(self):
        return {f"{g}-{s}" for g in range(self.gun_sayisi) for s in range(self.saat_sayisi)}


class DersMazeretBildirimi(models.Model):
    donem = models.ForeignKey(DersMazeretDonemi, on_delete=models.CASCADE, related_name="bildirimler")
    personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="ders_mazeretleri")
    hucreler = models.JSONField("Mazeretli saatler", default=dict, blank=True,
                                help_text='{"gün-saat": "no" | "maybe"}; gün ve saat 0\'dan başlar.')
    aciklama = models.TextField("Açıklama", blank=True)
    bildiren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)
    surum = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = "Ders mazeret bildirimi"
        verbose_name_plural = "Ders mazeret bildirimleri"
        constraints = [models.UniqueConstraint(fields=["donem", "personel"], name="ders_mazeret_tekil")]

    def __str__(self):
        return f"{self.donem}: {self.personel.ad_soyad}"

    @property
    def yasak_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == YASAK)

    @property
    def kosullu_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == KOSULLU)


class DersMazeretGecmisi(models.Model):
    """Her kaydın anlık görüntüsü (kim, ne zaman, ne bildirdi)."""

    bildirim = models.ForeignKey(DersMazeretBildirimi, on_delete=models.CASCADE, related_name="gecmis")
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now_add=True)
    hucreler = models.JSONField(default=dict)
    aciklama = models.TextField(blank=True)

    class Meta:
        verbose_name = "Bildirim geçmişi"
        verbose_name_plural = "Bildirim geçmişi"
        ordering = ["-zaman"]


class SinavMazeretDonemi(models.Model):
    """Bir sınav dönemi için oturum bazında mazeret bildirimi (PPYS SMS). Gün ve oturumlar bağlı sınav döneminden
    okunur; oturum saati sonradan değişirse o saate verilmiş işaretler geçersiz kalır (ekranda uyarılır)."""

    ad = models.CharField("Ad", max_length=80, help_text="ör. 2026-2027 Güz Vize")
    sinav_donemi = models.OneToOneField(
        "sinav.ExamPeriod", on_delete=models.SET_NULL, null=True, blank=True, related_name="mazeret_donemi",
        verbose_name="Sınav Planlama'daki sınav dönemi",
        help_text="Günler ve oturum saatleri buradan alınır; bildirimler bu dönemin gözetmen müsaitliğine yazılır.",
    )
    giris_acik = models.BooleanField("Bildirime açık", default=True)
    son_bildirim = models.DateTimeField(
        "Son bildirim zamanı", null=True, blank=True,
        help_text="Bu zamandan sonra bölümler değişiklik yapamaz (yöneticiler yapabilir). Boş = süresiz.",
    )
    bildirimsize_gorev_yok = models.BooleanField(
        "Bildirim yapmayana görev verilmesin", default=True,
        help_text="PPYS kuralı: bildirimi olmayan personel gözetmen dağıtımında hiçbir oturuma atanmaz.",
    )
    aciklama = models.TextField("Bölümlere not", blank=True)
    olusturma = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sınav mazeret dönemi"
        verbose_name_plural = "Sınav mazeret dönemleri"
        ordering = ["-olusturma"]

    def __str__(self):
        return self.ad

    @property
    def acik_mi(self):
        return self.giris_acik and (self.son_bildirim is None or timezone.now() <= self.son_bildirim)

    def tarihler(self):
        return self.sinav_donemi.dates() if self.sinav_donemi else []

    def oturumlar(self):
        return self.sinav_donemi.session_times if self.sinav_donemi else []

    def izgara(self):
        oturumlar = self.oturumlar()
        satirlar = []
        for t in self.tarihler():
            etiket = f"{t:%d.%m.%Y} {GUN_ADLARI[t.weekday()]}"
            satirlar.append((etiket, [(f"{t.isoformat()} {o}", f"{etiket} {o}") for o in oturumlar]))
        return oturumlar, satirlar

    def anahtarlar(self):
        return {f"{t.isoformat()} {o}" for t in self.tarihler() for o in self.oturumlar()}


class SinavMazeretBildirimi(models.Model):
    donem = models.ForeignKey(SinavMazeretDonemi, on_delete=models.CASCADE, related_name="bildirimler")
    personel = models.ForeignKey(Personel, on_delete=models.PROTECT, related_name="sinav_mazeretleri")
    hucreler = models.JSONField("Mazeretli oturumlar", default=dict, blank=True,
                                help_text='{"YYYY-AA-GG SS:DD": "no" | "maybe"}')
    aciklama = models.TextField("Açıklama", blank=True)
    bildiren = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    guncelleme = models.DateTimeField(auto_now=True)
    surum = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = "Sınav mazeret bildirimi"
        verbose_name_plural = "Sınav mazeret bildirimleri"
        constraints = [models.UniqueConstraint(fields=["donem", "personel"], name="sinav_mazeret_tekil")]

    def __str__(self):
        return f"{self.donem}: {self.personel.ad_soyad}"

    @property
    def yasak_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == YASAK)

    @property
    def kosullu_sayisi(self):
        return sum(1 for v in self.hucreler.values() if v == KOSULLU)


class SinavMazeretGecmisi(models.Model):
    """Her kayıtta bildirimin tam anlık görüntüsü."""

    bildirim = models.ForeignKey(SinavMazeretBildirimi, on_delete=models.CASCADE, related_name="gecmis")
    kullanici = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField(auto_now_add=True)
    hucreler = models.JSONField(default=dict)
    aciklama = models.TextField(blank=True)

    class Meta:
        verbose_name = "Bildirim geçmişi"
        verbose_name_plural = "Bildirim geçmişi"
        ordering = ["-zaman"]


class MazeretTeslimi(models.Model):
    """Bölümün bir mazeret dönemindeki bildirimini "tamamladık" diye teslim etmesi (ders ya da sınav). Teslimden sonra da
    değişiklik yapılabilir (dönem açıksa); sonradan değişen bildirimler ekranda işaretlenir."""

    tur = models.CharField("Tür", max_length=6, choices=[("ders", "Ders mazereti"), ("sinav", "Sınav mazereti")])
    donem_id = models.PositiveIntegerField("Dönem")
    bolum = models.ForeignKey("personel.Bolum", on_delete=models.CASCADE, related_name="mazeret_teslimleri")
    teslim_eden = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField("Teslim zamanı", auto_now=True)

    class Meta:
        verbose_name = "Mazeret teslimi"
        verbose_name_plural = "Mazeret teslimleri"
        constraints = [models.UniqueConstraint(fields=["tur", "donem_id", "bolum"], name="mazeret_teslimi_tekil")]

    def __str__(self):
        return f"{self.bolum} · {self.get_tur_display()} · {self.zaman:%d.%m.%Y %H:%M}"
