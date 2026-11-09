from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import servis
from .models import Bildirim, BildirimTercihi

PENCERE_DAKIKA = 10  # bundan eski bildirim sağ altta pencere olarak çıkmaz (yalnız zilde)


@require_GET
@login_required
def durum(request):
    """Sayfalardaki zil her 30 sn'de bir sorar: okunmamış sayısı ve `son`dan sonraki yeni bildirimler."""
    servis.zamanli_isler()
    son = request.GET.get("son", "")
    yeni = []
    if son.isdigit():
        sessizler = {t for t, m in servis.tercihler(request.user).items() if m == BildirimTercihi.SESSIZ}
        qs = Bildirim.objects.filter(kullanici=request.user, pk__gt=int(son), okundu__isnull=True,
                                     olusturma__gte=timezone.now() - timedelta(minutes=PENCERE_DAKIKA))
        yeni = [servis.sozluk(b, sessizler) for b in qs.order_by("pk")[:5]]
    en_son = Bildirim.objects.filter(kullanici=request.user).values_list("pk", flat=True).first() or 0
    return JsonResponse({"okunmamis": servis.okunmamis_sayisi(request.user), "son": en_son, "yeni": yeni})


@require_GET
@login_required
def liste(request):
    sinir = timezone.now() - timedelta(days=servis.SAKLAMA_GUNU)
    kayitlar = list(Bildirim.objects.filter(kullanici=request.user, olusturma__gte=sinir)[:60])
    bugun = timezone.localdate()
    for b in kayitlar:
        b.d = servis.sozluk(b)
        gun = timezone.localtime(b.olusturma).date()
        b.gun = "Bugün" if gun == bugun else "Dün" if gun == bugun - timedelta(days=1) else f"{gun:%d.%m.%Y}"
    return render(request, "bildirim/_liste.html", {"kayitlar": kayitlar,
                                                     "okunmamis": servis.okunmamis_sayisi(request.user)})


@require_GET
@login_required
def ayarlar(request):
    return render(request, "bildirim/_ayarlar.html", {"satirlar": servis.ayar_satirlari(request.user),
                                                       "modlar": BildirimTercihi.MODLAR})


@require_POST
@login_required
def tercih(request):
    try:
        servis.tercih_yaz(request.user, request.POST.get("tur", ""), request.POST.get("mod", ""))
    except ValueError:
        raise Http404("Geçersiz bildirim türü.")
    return JsonResponse({"tamam": True})


@require_POST
@login_required
def okundu(request):
    qs = Bildirim.objects.filter(kullanici=request.user, okundu__isnull=True)
    pk = request.POST.get("id", "")
    if pk.isdigit():
        qs = qs.filter(pk=int(pk))
    qs.update(okundu=timezone.now())
    return JsonResponse({"okunmamis": servis.okunmamis_sayisi(request.user)})


@login_required
def ac(request, pk):
    b = get_object_or_404(Bildirim, pk=pk, kullanici=request.user)
    if b.okundu is None:
        Bildirim.objects.filter(pk=b.pk).update(okundu=timezone.now())
    if b.url and url_has_allowed_host_and_scheme(b.url, allowed_hosts={request.get_host()}, require_https=False):
        return redirect(b.url)
    return redirect("core:panel")
