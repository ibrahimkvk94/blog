from django.conf import settings

from .kisayollar import bolum_hesabi_mi, kisayollar
from .yetki import menu_agaci


def navigation(request):
    ctx = {"kurum_adi": settings.KURUM_ADI, "sistem_adi": settings.SISTEM_ADI}
    if request.user.is_authenticated and not request.path.startswith("/yonetim/"):
        # bölüm hesabının menüsünde yalnızca kısayollar var: birim ağacı ve organizasyon şeması gizli
        ctx["bolum_hesabi"] = bolum_hesabi_mi(request.user)
        ctx["menu"] = [] if ctx["bolum_hesabi"] else menu_agaci(request)
        ctx["kisayollar"] = kisayollar(request)
    return ctx
