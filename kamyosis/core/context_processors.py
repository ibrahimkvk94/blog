from django.conf import settings

from .kisayollar import acik_sayfalar, bolum_hesabi_mi, kisayollar, menuden_ayikla, yildizli_idler
from .yetki import menu_agaci


def navigation(request):
    ctx = {"kurum_adi": settings.KURUM_ADI, "sistem_adi": settings.SISTEM_ADI}
    if request.user.is_authenticated and not request.path.startswith("/yonetim/"):
        # herkes yetkili olduğu birim ağacını görür (bölüme kapatılan sayfalar hariç); kısayollar = yıldızlananlar
        ctx["bolum_hesabi"] = bolum_hesabi_mi(request.user)
        ctx["menu"] = menuden_ayikla(request.user, menu_agaci(request))
        ctx["kisayollar"] = kisayollar(request)
        ctx["yildizli"] = set(yildizli_idler(request))
        ctx["acik_sayfalar"] = acik_sayfalar(request)
        for b in ctx["acik_sayfalar"]:
            b.secili = getattr(getattr(request, "birim", None), "pk", None) == b.pk
        from isler.servis import sahibi_mi

        ctx["is_listesi_sahibi"] = sahibi_mi(request.user)
        from bildirim.models import Bildirim

        bildirimler = Bildirim.objects.filter(kullanici=request.user)
        ctx["bildirim_okunmamis"] = bildirimler.filter(okundu__isnull=True).count()
        ctx["bildirim_son"] = bildirimler.values_list("pk", flat=True).first() or 0
    return ctx
