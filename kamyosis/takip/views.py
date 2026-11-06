from collections import OrderedDict
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum, Personel
from program.models import Kisim

from . import servis
from .models import DevirTalebi, Tatil
from .servis import TakipHatasi


def _tarih(deger, varsayilan=None):
    try:
        return date.fromisoformat(deger)
    except (TypeError, ValueError):
        return varsayilan or timezone.localdate()


def _baglam(request, **ek):
    request.birim = birim_bul(request, servis.BIRIM_DERS)
    return {"yol": yol(request, request.birim), "y": servis.yetki(request), "breadcrumb_ek": True, **ek}


def _geri(request, varsayilan):
    hedef = request.POST.get("geri") or request.GET.get("geri")
    if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        return redirect(hedef)
    return redirect(varsayilan)


@login_required
def gunluk(request):
    y = servis.yetki(request)
    if not y.goruntule:
        if y.personel is not None:
            return redirect("takip:derslerim")
        raise PermissionDenied
    tarih = _tarih(request.GET.get("tarih"))
    # Aralık görünümü (ana sayfadan gelen "son 14 gün" bağlantıları): ?bas=...&bit=...
    bas = _tarih(request.GET.get("bas"), None) if request.GET.get("bas") else None
    bit = _tarih(request.GET.get("bit"), None) if request.GET.get("bit") else None
    if bas and bit and bas <= bit:
        bas = max(bas, bit - timedelta(days=31))
    else:
        bas = bit = None
    bolum = y.kapsam_bolum
    if bolum is None and request.GET.get("bolum", "").isdigit():
        bolum = Bolum.objects.filter(pk=request.GET["bolum"]).first()
    kisim = Kisim.objects.filter(pk=request.GET["kisim"]).first() if request.GET.get("kisim", "").isdigit() else None
    durum = request.GET.get("durum", "")
    satirlar = servis.beklenen_dersler(bas or tarih, bit or tarih, bolum=bolum, kisim=kisim)
    sayilar = {d: sum(1 for s in satirlar if s.durum == d) for d in ("yapildi", "gelecek", "devir")}
    if durum:
        satirlar = [s for s in satirlar if s.durum == durum]
    for s in satirlar:
        s.talep_edebilir = servis.talep_yetkisi_var(y, s)
    return render(request, "takip/gunluk.html", _baglam(
        request, tarih=tarih, onceki=tarih - timedelta(days=1), sonraki=tarih + timedelta(days=1), bas=bas, bit=bit,
        bugun=timezone.localdate(), satirlar=satirlar, sayilar=sayilar, durum=durum,
        tatil=Tatil.objects.filter(tarih=tarih).first(),
        bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [], secili_bolum=bolum,
        kisimlar=sorted(Kisim.objects.filter(bolum=bolum) if bolum else Kisim.objects.all(), key=lambda k: (k.sira_no == 0, k.sira_no, k.kod)),
        secili_kisim=kisim,
    ))


@login_required
def derslerim(request):
    y = servis.yetki(request)
    if y.personel is None:
        messages.info(request, "Hesabınız bir personel kaydına bağlı değil. Sistem yöneticisinden bağlanmasını isteyin.")
        return redirect("core:panel")
    tarih = _tarih(request.GET.get("tarih"))
    pazartesi = tarih - timedelta(days=tarih.weekday())
    satirlar = servis.beklenen_dersler(pazartesi, pazartesi + timedelta(days=6), personel=y.personel)
    gunler = OrderedDict()
    for s in satirlar:
        gunler.setdefault(s.tarih, []).append(s)
    return render(request, "takip/derslerim.html", {
        "y": y, "pazartesi": pazartesi, "onceki": pazartesi - timedelta(days=7), "sonraki": pazartesi + timedelta(days=7),
        "bugun": timezone.localdate(), "gunler": gunler, "toplam": len(satirlar),
        "yapilan": sum(1 for s in satirlar if s.yapildi),
    })


@login_required
def devir_yeni(request):
    y = servis.yetki(request)
    if not y.bolum_adina:
        raise PermissionDenied
    anahtarlar = request.POST.getlist("d") or request.GET.getlist("d")
    try:
        satirlar = servis.satirlari_getir(anahtarlar)
    except TakipHatasi as e:
        messages.error(request, str(e))
        return _geri(request, "takip:gunluk")
    hata = None
    if request.method == "POST":
        p = Personel.objects.filter(pk=request.POST.get("personel"), aktif=True).first()
        if p is None:
            hata = "Devralacak personeli seçin."
        else:
            try:
                servis.devir_talep_et(request.user, y, satirlar, p, request.POST.get("gerekce"))
                messages.success(request, f"{len(satirlar)} ders için devir talebi oluşturuldu.")
                return redirect("takip:devirler")
            except TakipHatasi as e:
                hata = str(e)
    return render(request, "takip/devir_yeni.html", _baglam(
        request, satirlar=satirlar, hata=hata, geri=request.GET.get("geri", ""),
        personeller=Personel.objects.filter(aktif=True, derse_girebilir=True).select_related("bolum").order_by("ad_soyad"),
        secili_personel=request.POST.get("personel", ""), gerekce=request.POST.get("gerekce", ""),
    ))


@login_required
def devirler(request):
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    sekme = request.GET.get("durum", "bekleyen")
    qs = DevirTalebi.objects.select_related(
        "kayit__hucre__haftalik_ders__ders", "kayit__hucre__derslik", "kayit__ogretmen__personel__bolum",
        "kayit__ogretmen__tahmini_bolum", "yeni_personel__bolum", "isteyen", "karar_veren",
    ).prefetch_related("kayit__hucre__haftalik_ders__kisimlar")
    if sekme == "bekleyen":
        qs = qs.filter(durum__in=DevirTalebi.BEKLEYEN)
    elif sekme in dict(DevirTalebi.DURUM_SECENEKLERI):
        qs = qs.filter(durum=sekme)
    gruplar = OrderedDict()
    for t in qs[:600]:
        asil = t.kayit.ogretmen.personel
        asil_bolum = asil.bolum if asil else t.kayit.ogretmen.tahmini_bolum
        if not (y.bolumu_kapsar(asil_bolum) or y.bolumu_kapsar(t.yeni_personel.bolum)):
            continue
        gruplar.setdefault(t.blok, []).append(t)
    sayilar = {
        "bekleyen": DevirTalebi.objects.filter(durum__in=DevirTalebi.BEKLEYEN).values("blok").distinct().count(),
        **{d: DevirTalebi.objects.filter(durum=d).values("blok").distinct().count() for d, _ in DevirTalebi.DURUM_SECENEKLERI},
    }
    sekmeler = [("bekleyen", "Bekleyen")] + [(d, a) for d, a in DevirTalebi.DURUM_SECENEKLERI if d not in DevirTalebi.BEKLEYEN]
    return render(request, "takip/devirler.html", _baglam(
        request, gruplar=[(blok, sorted(ts, key=lambda t: (t.kayit.tarih, t.kayit.hucre.saat))) for blok, ts in gruplar.items()],
        sekme=sekme, sekmeler=[(k, a, sayilar.get(k, 0)) for k, a in sekmeler],
    ))


@require_POST
@login_required
def devir_karar(request, blok):
    y = servis.yetki(request)
    try:
        talepler = servis.devir_karar(request.user, y, blok, request.POST.get("islem"), request.POST.get("not"))
        messages.success(request, f"{len(talepler)} derslik devir talebi: {talepler[0].get_durum_display().lower()}.")
    except TakipHatasi as e:
        messages.error(request, str(e))
    return _geri(request, "takip:devirler")


def _kisi(s, personel):
    """Rapor satırı anahtarı ve adı: personel varsa o, yoksa programdaki aSc öğretmeni."""
    if personel is not None:
        return ("p", personel.pk), personel.ad_soyad, personel.bolum
    return ("o", s.ogretmen.pk), s.ogretmen.ad, s.ogretmen.tahmini_bolum


@login_required
def rapor(request):
    """Yapılan ders raporu: tarihi geçen her ders yapılmış sayılır; devirler etkin öğretmene yazılır."""
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    dun = timezone.localdate() - timedelta(days=1)
    bit = min(_tarih(request.GET.get("bit"), dun), dun)
    bas = _tarih(request.GET.get("bas"), bit.replace(day=1))
    if bas > bit:
        bas = bit
    if (bit - bas).days > 92:
        bas = bit - timedelta(days=92)
        messages.info(request, "Rapor en fazla 3 aylık aralık için hazırlanır.")
    bolum = y.kapsam_bolum
    if bolum is None and request.GET.get("bolum", "").isdigit():
        bolum = Bolum.objects.filter(pk=request.GET["bolum"]).first()
    satirlar = servis.beklenen_dersler(bas, bit, bolum=bolum)
    kisiler = {}

    def kisi(s, personel):
        anahtar, ad, kisi_bolum = _kisi(s, personel)
        return kisiler.setdefault(anahtar, {"ad": ad, "bolum": kisi_bolum, "yapilan": 0, "devralinan": 0, "devredilen": 0})

    for s in satirlar:
        devirli = s.etkin_personel != s.asil_personel
        if bolum is None or s.bolum == bolum:
            etkin = kisi(s, s.etkin_personel)
            etkin["yapilan"] += 1
            etkin["devralinan"] += devirli
        if devirli and (bolum is None or s.asil_bolum == bolum):
            kisi(s, s.asil_personel)["devredilen"] += 1
    liste = sorted((k for k in kisiler.values() if k["yapilan"] or k["devredilen"]), key=lambda k: k["ad"])
    return render(request, "takip/rapor.html", _baglam(
        request, bas=bas, bit=bit, liste=liste, toplam=sum(k["yapilan"] for k in liste),
        devir_toplam=sum(k["devralinan"] for k in liste),
        bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [], secili_bolum=bolum,
    ))
