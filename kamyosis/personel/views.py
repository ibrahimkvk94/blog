from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Yetki
from core.yetki import DUZENLEME, yetki_gerekli, yol

from .forms import PersonelForm
from .models import Bolum, Personel, Secenek

BIRIM = "personel-bilgileri"


def _kapsamli(request):
    qs = Personel.objects.select_related("bolum", "rutbe", "sinif", "unvan")
    if request.yetki_kapsam == Yetki.BOLUM:
        return qs.filter(bolum_id=request.user.bolum_id) if request.user.bolum_id else qs.none()
    return qs


def _sabit_bolum(request):
    return request.user.bolum if request.yetki_kapsam == Yetki.BOLUM else None


@yetki_gerekli(BIRIM)
def liste(request):
    qs = _kapsamli(request)
    q = request.GET.get("q", "").strip()
    bolum = request.GET.get("bolum", "")
    rutbe = request.GET.get("rutbe", "")
    durum = request.GET.get("durum", "aktif")
    if q:
        kosul = Q(ad_soyad__icontains=q) | Q(sicil__icontains=q)
        if request.yetki_seviye >= DUZENLEME:  # kimlik no ile arama, numarayı yoklamaya açık olmasın
            kosul |= Q(personel_kodu__icontains=q)
        qs = qs.filter(kosul)
    if bolum.isdigit():
        qs = qs.filter(bolum_id=bolum)
    if rutbe.isdigit():
        qs = qs.filter(rutbe_id=rutbe)
    if durum == "aktif":
        qs = qs.filter(aktif=True)
    elif durum == "pasif":
        qs = qs.filter(aktif=False)

    sayfa = Paginator(qs, 25).get_page(request.GET.get("sayfa"))
    sorgu = request.GET.copy()
    sorgu.pop("sayfa", None)
    return render(request, "personel/liste.html", {
        "sayfa": sayfa,
        "toplam": qs.count(),
        "q": q, "secili_bolum": bolum, "secili_rutbe": rutbe, "durum": durum,
        "bolumler": Bolum.objects.filter(aktif=True) if request.yetki_kapsam == Yetki.TUM else [],
        "rutbeler": Secenek.objects.filter(tur=Secenek.RUTBE, aktif=True),
        "sorgu": sorgu.urlencode(),
        "duzenleyebilir": request.yetki_seviye >= DUZENLEME,
        "yol": yol(request, request.birim),
    })


@yetki_gerekli(BIRIM)
def detay(request, pk):
    p = get_object_or_404(_kapsamli(request), pk=pk)
    return render(request, "personel/detay.html", {
        "p": p,
        "duzenleyebilir": request.yetki_seviye >= DUZENLEME,
        "yol": yol(request, request.birim),
        "breadcrumb_ek": True,
    })


@yetki_gerekli(BIRIM, DUZENLEME)
def ekle(request):
    return _form(request, None)


@yetki_gerekli(BIRIM, DUZENLEME)
def duzenle(request, pk):
    return _form(request, get_object_or_404(_kapsamli(request), pk=pk))


def _form(request, nesne):
    form = PersonelForm(request.POST or None, instance=nesne, sabit_bolum=_sabit_bolum(request))
    if request.method == "POST" and form.is_valid():
        p = form.save()
        messages.success(request, f"{p.ad_soyad} kaydedildi.")
        return redirect("personel:detay", pk=p.pk)
    return render(request, "personel/form.html", {
        "form": form, "nesne": nesne, "yol": yol(request, request.birim), "breadcrumb_ek": True,
    })
