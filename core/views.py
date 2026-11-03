from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from personel.models import Bolum, Personel

from .models import Birim
from .yetki import gorunur_cocuklar, gorunur_mu, menu_agaci, birim_bul, yol


def _selam():
    saat = timezone.localtime().hour
    if 5 <= saat < 12:
        return "Günaydın"
    if 12 <= saat < 18:
        return "İyi günler"
    return "İyi akşamlar"


def _gorunen_ad(user):
    if user.get_full_name():
        return user.get_full_name()
    if user.bolum_id and not user.is_superuser:
        return f"{user.bolum.ad} bölümü"
    return user.username


@login_required
def panel(request):
    from mazeret.servis import panel_gorevleri as mazeret_gorevleri
    from takip.servis import panel_gorevleri

    return render(request, "core/panel.html", {
        "selam": _selam(), "gorunen_ad": _gorunen_ad(request.user), "bugun": timezone.localdate(),
        "gorevler": panel_gorevleri(request, ek=mazeret_gorevleri(request)),
        "kokler": menu_agaci(request),
    })


@login_required
def organizasyon(request):
    kokler = menu_agaci(request)
    ozet = None
    if request.user.is_superuser:
        gorevler = Birim.objects.filter(aktif=True, tur=Birim.GOREV)
        ozet = {
            "durumlar": [(kod, ad, gorevler.filter(durum=kod).count()) for kod, ad in Birim.DURUM_SECENEKLERI],
            "personel": Personel.objects.filter(aktif=True).count(),
            "bolum": Bolum.objects.filter(aktif=True).count(),
            "kullanici": get_user_model().objects.filter(is_active=True).count(),
        }
    return render(request, "core/organizasyon.html", {"kokler": kokler, "ozet": ozet, "breadcrumb_ek": True})


@login_required
def birim(request, slug):
    b = birim_bul(request, slug)
    if not gorunur_mu(request, b):
        raise PermissionDenied
    cocuklar = gorunur_cocuklar(request, b)
    if b.modul_url:
        return redirect(b.get_absolute_url())
    request.birim = b
    return render(request, "core/birim.html", {"b": b, "cocuklar": cocuklar, "yol": yol(request, b)})


@login_required
def bolum_yetkileri(request):
    """Bölüm hesaplarının hangi modülleri göreceği: satır = bölüm, sütun = modül (yalnızca sistem yöneticisi)."""
    from django.contrib import messages

    from . import bolum_yetkileri as by

    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method == "POST":
        secim = {}
        for deger in request.POST.getlist("h"):
            bolum_id, _, birim_id = deger.partition("-")
            if bolum_id.isdigit() and birim_id.isdigit():
                secim.setdefault(int(bolum_id), set()).add(int(birim_id))
        seviyeler = {int(k[7:]): int(v) for k, v in request.POST.items() if k.startswith("seviye_") and k[7:].isdigit() and v.isdigit()}
        n = by.kaydet(secim, seviyeler)
        messages.success(request, f"Bölüm yetkileri kaydedildi ({n} değişiklik)." if n else "Değişiklik yok.")
        return redirect("core:bolum_yetkileri")
    moduller, satirlar, sutun_seviye = by.tablo()
    gruplar = []
    for m in moduller:
        if gruplar and gruplar[-1]["grup"] == m.grup:
            gruplar[-1]["sayi"] += 1
        else:
            gruplar.append({"grup": m.grup, "sayi": 1})
    for m in moduller:
        m.seviye = sutun_seviye[m.id]
        m.yalniz_gorur = m.slug in by.YALNIZ_GORUR
    hesapsiz = Bolum.objects.filter(aktif=True).exclude(pk__in=[s["bolum"].pk for s in satirlar])
    return render(request, "core/bolum_yetkileri.html", {
        "moduller": moduller, "satirlar": satirlar, "gruplar": gruplar, "seviyeler": by.SEVIYELER,
        "hesapsiz": hesapsiz, "breadcrumb_ek": True,
    })
