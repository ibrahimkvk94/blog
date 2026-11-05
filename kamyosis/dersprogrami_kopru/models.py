"""KAMYOSİS'in Sınav Planlama modülüne eklediği kayıtlar."""

from django.conf import settings
from django.db import models


class SinavYayini(models.Model):
    """Yayınlanan sınav dönemi. Sınav Planları biriminde yalnız görüntüleme yetkisi olanlar (bölümler) planlama
    aşamalarını görmez; yalnızca yayınlanan dönemlerin sınav programını ve görevlendirmeleri görür. Yayındaki dönemde
    sonradan yapılan düzeltmeler (ör. görev değişikliği) yayına hemen yansır; baştan çalışmak için yayından kaldırılır."""

    donem = models.OneToOneField("sinav.ExamPeriod", on_delete=models.CASCADE, related_name="kamyosis_yayini",
                                 verbose_name="Sınav dönemi")
    yayinlayan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    zaman = models.DateTimeField("Yayın zamanı", auto_now=True)

    class Meta:
        verbose_name = "Sınav programı yayını"
        verbose_name_plural = "Sınav programı yayınları"

    def __str__(self):
        return f"{self.donem} · yayında"
