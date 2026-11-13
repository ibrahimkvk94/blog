from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from personel.models import Bolum, Personel

from . import istatistik, pano
from .kisayollar import gizli_kodlar, kapali_mi
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


def _cozumle(url):
    from django.urls import Resolver404, resolve

    try:
        return resolve(url.split("?")[0])
    except Resolver404:
        return None


@login_required
def panel(request):
    from mazeret.servis import panel_gorevleri as mazeret_gorevleri
    from takip.servis import panel_gorevleri
    from yoklama.servis import panel_gorevleri as yoklama_gorevleri
    from vekalet.servis import panel_gorevleri as vekalet_gorevleri

    from isler.gorevler import panel_gorevleri as is_gorevleri

    gorevler = panel_gorevleri(request, ek=[*is_gorevleri(request), *yoklama_gorevleri(request),
                                            *mazeret_gorevleri(request), *vekalet_gorevleri(request)])
    if gizli_kodlar(request.user):  # bölüme kapatılmış kısayolların görev kartları gösterilmez
        gorevler = [g for g in gorevler if not (g.get("url") and kapali_mi(request.user, _cozumle(g["url"])))]
    return render(request, "core/panel.html", {
        "selam": _selam(), "gorunen_ad": _gorunen_ad(request.user), "bugun": timezone.localdate(),
        "gorevler": gorevler,
        "kokler": menu_agaci(request),
    })


@login_required
def istatistikler(request):
    """İstatistikler: "Bugün" (günlük gösterge paneli) ve "Personel" (kadro yapısı). Yalnız sistem yöneticileri."""
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method == "POST" and request.POST.get("islem") == "kapasite":
        return _kapasite_kaydet(request)
    sekme = request.GET.get("sekme")
    if sekme not in ("bugun", "personel"):
        sekme = "bugun"
    ctx = {"sekme": sekme}
    if sekme == "bugun":
        ctx["pano"] = pano.hazirla(request)
    else:
        ctx["kadro"] = istatistik.kadro()
    return render(request, "core/istatistikler.html", ctx)


def _kapasite_kaydet(request):
    """Kadro kapasitesi formu (İstatistikler · Personel). Boş bırakılan kutu "girilmedi" demektir."""
    from django.contrib import messages

    from .models import KadroKapasitesi

    k = KadroKapasitesi.al()
    hatali = False
    for alan in ("toplam", "subay", "astsubay", "sivil"):
        deger = request.POST.get(alan, "").strip()
        if not deger:
            setattr(k, alan, None)
        elif deger.isdigit() and int(deger) <= 100000:
            setattr(k, alan, int(deger))
        else:
            hatali = True
    if hatali:
        messages.error(request, "Kapasite kutularına yalnız tam sayı yazılabilir; kaydedilmedi.")
    else:
        k.guncelleyen = request.user
        k.save()
        messages.success(request, "Kadro kapasitesi kaydedildi.")
    return redirect(reverse("core:istatistikler") + "?sekme=personel#doluluk")


@login_required
def organizasyon(request):
    """Organizasyon şeması: "Organizasyon Şeması" biriminde görüntüleme yetkisi olanlar (yetki tablosundan açılır)."""
    from .yetki import GORUNTULEME, etkin_yetki

    try:
        request.birim = birim_bul(request, "organizasyon-semasi")
    except Http404:
        request.birim = None
    if not request.user.is_superuser and (request.birim is None or
                                          etkin_yetki(request, request.birim)[0] < GORUNTULEME):
        raise PermissionDenied
    kokler = [k for k in menu_agaci(request) if k.slug != "organizasyon-semasi"]
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
    if request.GET.get("eski") != "1":  # sayfa "Kullanıcılar ve yetkiler"e taşındı
        return redirect(reverse("core:kullanicilar") + "?tur=bolum")
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


@login_required
def bolum_kisayollari(request):
    """Bölüm hesaplarının menüsünde hangi kısayolların görüneceği: satır = bölüm, sütun = kısayol (sistem yöneticisi)."""
    from django.contrib import messages

    from . import bolum_yetkileri as by
    from .kisayollar import KISAYOLLAR
    from .models import BolumMenusu

    if not request.user.is_superuser:
        raise PermissionDenied
    hesaplar = by.bolum_hesaplari()
    bolumler = {}
    for u in hesaplar:
        bolumler.setdefault(u.bolum, []).append(u)
    kodlar = [k[0] for k in KISAYOLLAR]
    if request.method == "POST":
        acik = set(request.POST.getlist("k"))
        n = 0
        for b in bolumler:
            gizli = [kod for kod in kodlar if f"{b.pk}:{kod}" not in acik]
            ayar, _ = BolumMenusu.objects.get_or_create(bolum=b)
            if ayar.gizli != gizli:
                ayar.gizli = gizli
                ayar.save(update_fields=["gizli"])
                n += 1
        messages.success(request, f"Bölüm kısayolları kaydedildi ({n} bölüm değişti)." if n else "Değişiklik yok.")
        return redirect("core:bolum_kisayollari")
    gizli = {m.bolum_id: set(m.gizli) for m in BolumMenusu.objects.all()}
    satirlar = [{"bolum": b, "hesaplar": us,
                 "hucreler": [{"kod": kod, "acik": kod not in gizli.get(b.pk, set())} for kod in kodlar]}
                for b, us in sorted(bolumler.items(), key=lambda kv: kv[0].ad)]
    return render(request, "core/bolum_kisayollari.html", {
        "kisayol_listesi": [{"kod": k[0], "ad": k[2], "ikon": k[3]} for k in KISAYOLLAR], "satirlar": satirlar})


@require_POST
@login_required
def kisayol_degistir(request, pk):
    """Menüdeki yıldız: sayfayı kullanıcının kısayollarına ekler ya da çıkarır. Dönüş: yeni durum ve menünün
    Kısayollar bölümü (sayfa yenilenmeden güncellenir)."""
    from django.db.models import Max
    from django.http import JsonResponse
    from django.template.loader import render_to_string

    from .kisayollar import kisayollar, yildizlanabilir_mi
    from .models import Kisayol
    from .yetki import agac

    by_id, _ = agac(request)
    b = by_id.get(pk)
    if b is None or not yildizlanabilir_mi(request, b):
        raise Http404
    silinen, _ = Kisayol.objects.filter(kullanici=request.user, birim_id=pk).delete()
    if not silinen:
        son = Kisayol.objects.filter(kullanici=request.user).aggregate(m=Max("sira"))["m"] or 0
        Kisayol.objects.create(kullanici=request.user, birim_id=pk, sira=son + 1)
    request.__dict__.pop("_yildizli", None)
    html = render_to_string("partials/kisayol_listesi.html", {"kisayollar": kisayollar(request)}, request=request)
    return JsonResponse({"yildizli": not silinen, "html": html})
