from django.contrib import messages
from django.shortcuts import redirect, render

from core.yetki import yetki_gerekli
from timetable.access import visible_schools

from .yetki import SINAV_BIRIMI


@yetki_gerekli(SINAV_BIRIMI)
def sinavlar(request):
    """Sınav Planları birimi: Sınav Planlama modülünde yayındaki (yoksa en son eklenen) programın sınav dönemleri."""
    okullar = visible_schools(request.user)
    okul = okullar.filter(active_timetable__isnull=False).order_by("-pk").first() or okullar.order_by("-pk").first()
    if okul is None:
        from timetable.models import School

        okul = School.objects.filter(active_timetable__isnull=False).order_by("-pk").first()
    if okul is None:
        from .middleware import sadece_sinav

        if sadece_sinav(request):  # modülün program listesine giremez; yönlendirme döngüsü olmasın
            return render(request, "dersprogrami_kopru/kapali.html", {"neden": "Henüz sınav programı hazırlanmadı."})
        messages.info(request, "Sınav programı, Ders Programı modülündeki bir programa bağlıdır. Önce program ekleyin.")
        return redirect("timetable:school_list")
    return redirect("sinav:periods", pk=okul.pk)
