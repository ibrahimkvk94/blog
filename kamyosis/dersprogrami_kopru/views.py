from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect, render

from core.yetki import yetki_gerekli
from timetable.access import visible_schools

from .yetki import SINAV_BIRIMI


@yetki_gerekli(SINAV_BIRIMI)
def sinavlar(request):
    """Sınav Planları birimi: planlamacıya Sınav Planlama modülünde yayındaki (yoksa en son eklenen) programın sınav
    dönemleri; yalnız görüntüleyene yayınlanan sınav programları."""
    from .yetki import sinav_planlamacisi

    if not sinav_planlamacisi(request.user):
        return redirect("dersprogrami_kopru:sinav_programi")
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


MODUL_ONEKI = "/ders-programi/"


def _guvenli_modul_adresi(u):
    """Çerçevede yalnız bu sitenin Ders Programı / Sınav Planlama sayfaları açılır."""
    u = (u or "").strip()
    if not u.startswith((MODUL_ONEKI, "/ders-programi-kopru/sinavlar/")) or "//" in u or ".." in u or "\\" in u or any(ord(c) < 32 for c in u):
        return MODUL_ONEKI
    return u


@login_required
def cerceve(request):
    """Ders Programı / Sınav Planlama sayfalarını KAMYOSİS'in içinde (sol menü sabit) açar; adres çubuğu ve geri /
    ileri tuşları çerçevedeki sayfayı izler."""
    from core.yetki import birim_bul, yol

    u = _guvenli_modul_adresi(request.GET.get("u"))
    if u.startswith("/ders-programi-kopru/sinavlar/"):
        from .yetki import sinav_planlamacisi

        if not sinav_planlamacisi(request.user):  # görüntüleyen çerçevesiz yayın sayfasına
            return redirect("dersprogrami_kopru:sinav_programi")
    slug = "sinav-planlari" if u.startswith((MODUL_ONEKI + "sinav-planlama/", "/ders-programi-kopru/sinavlar/"))         else "program-hazirlama"
    try:
        request.birim = birim_bul(request, slug)
        baglam_yol = yol(request, request.birim)
    except Exception:  # birim yoksa da çerçeve açılsın
        baglam_yol = []
    return render(request, "dersprogrami_kopru/cerceve.html", {"u": u, "yol": baglam_yol})
