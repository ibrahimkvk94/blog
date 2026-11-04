"""Personel Kartları.

Yetki ("Personel Kartları" birimi):
- Görüntüleme / düzenleme: temel bilgiler (ad, sicil, bölüm, rütbe, sınıf, unvan) yetkisi kadar, bölüm kapsamlıysa
  yalnız kendi bölümü. T.C. kimlik no maskelidir.
- Yönetim (yönetici): T.C. kimlik no, ek kart alanları (telefon, adres …), fotoğraf, ders / sınav kullanımı,
  teşkilattaki yeri, görev unvanı, idari kadro ve bölüm başkanlığı; kart alanlarını ve teşkilat şemasını yönetir.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, ProtectedError, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import Yetki
from core.yetki import DUZENLEME, YONETIM, yetki_gerekli, yol

from . import kart
from .forms import KartAlaniFormu, PersonelForm, TeskilatFormu
from .models import Bolum, KartAlani, Personel, Secenek, TeskilatBirimi

BIRIM = "personel-bilgileri"


def _kapsamli(request):
    qs = Personel.objects.select_related("bolum", "rutbe", "sinif", "unvan", "teskilat_birimi")
    if request.yetki_kapsam == Yetki.BOLUM:
        return qs.filter(bolum_id=request.user.bolum_id) if request.user.bolum_id else qs.none()
    return qs


def _sabit_bolum(request):
    return request.user.bolum if request.yetki_kapsam == Yetki.BOLUM else None


def _yonetici(request):
    return request.yetki_seviye >= YONETIM


def _baglam(request, **ek):
    return {"yol": yol(request, request.birim), "yonetici": _yonetici(request),
            "duzenleyebilir": request.yetki_seviye >= DUZENLEME, **ek}


@yetki_gerekli(BIRIM)
def liste(request):
    qs = _kapsamli(request)
    q = request.GET.get("q", "").strip()
    bolum = request.GET.get("bolum", "")
    rutbe = request.GET.get("rutbe", "")
    durum = request.GET.get("durum", "aktif")
    if q:
        kosul = Q(ad_soyad__icontains=q) | Q(sicil__icontains=q)
        if _yonetici(request):  # kimlik no ile arama yalnız yöneticide
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
    return render(request, "personel/liste.html", _baglam(
        request, sayfa=sayfa, toplam=qs.count(), q=q, secili_bolum=bolum, secili_rutbe=rutbe, durum=durum,
        bolumler=Bolum.objects.filter(aktif=True) if request.yetki_kapsam == Yetki.TUM else [],
        rutbeler=Secenek.objects.filter(tur=Secenek.RUTBE, aktif=True), sorgu=sorgu.urlencode(), sekme="liste"))


@yetki_gerekli(BIRIM)
def detay(request, pk):
    p = get_object_or_404(_kapsamli(request), pk=pk)
    yonetici = _yonetici(request)
    return render(request, "personel/detay.html", _baglam(
        request, p=p, breadcrumb_ek=True, teskilat_yeri=kart.teskilattaki_yeri(p),
        kart_bilgileri=kart.kart_bilgileri(p, sadece_dolu=False) if yonetici else [],
        baskan_mi=bool(p.bolum_id and p.bolum.baskan_id == p.pk)))


@yetki_gerekli(BIRIM, DUZENLEME)
def ekle(request):
    return _form(request, None)


@yetki_gerekli(BIRIM, DUZENLEME)
def duzenle(request, pk):
    return _form(request, get_object_or_404(_kapsamli(request), pk=pk))


def _form(request, nesne):
    yonetici = _yonetici(request)
    form = PersonelForm(request.POST or None, instance=nesne, sabit_bolum=_sabit_bolum(request), yonetici=yonetici)
    if request.method == "POST" and form.is_valid():
        eski_sinav = nesne.sinav_gorevi_alabilir if nesne else True
        p = form.save()
        if yonetici:
            kart.kart_kaydet(p, request.POST)
            kart.baskan_ata(p, request.POST.get("bolum_baskani") == "1")
            if p.sinav_gorevi_alabilir != eski_sinav:
                _sinav_rollerini_esitle()
        messages.success(request, f"{p.ad_soyad} kaydedildi.")
        return redirect("personel:detay", pk=p.pk)
    return render(request, "personel/form.html", _baglam(
        request, form=form, nesne=nesne, breadcrumb_ek=True,
        kart_bilgileri=kart.kart_bilgileri(nesne or Personel()) if yonetici else [],
        baskan_mi=bool(nesne and nesne.bolum_id and nesne.bolum.baskan_id == nesne.pk)))


def _sinav_rollerini_esitle():
    """Sınav görevi alabilir değişti: bağlı sınav dönemlerindeki rolleri hemen güncelle (hata kaydı bozmasın)."""
    try:
        from sinavgorev.servis import rolleri_esitle

        rolleri_esitle()
    except Exception:  # sınav modülü yoksa ya da dönem yoksa sessizce geç
        pass


# ---------------------------------------------------------------- fotoğraf (yalnız yönetici yükler)

@yetki_gerekli(BIRIM)
def fotograf(request, pk):
    p = get_object_or_404(_kapsamli(request), pk=pk)
    if not p.fotograf:
        raise Http404
    try:
        cevap = FileResponse(p.fotograf.open("rb"), content_type="image/jpeg")
    except FileNotFoundError:
        raise Http404
    cevap["Cache-Control"] = "private, max-age=86400"
    return cevap


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def fotograf_yukle(request, pk):
    from yoklama import foto

    p = get_object_or_404(_kapsamli(request), pk=pk)
    if request.POST.get("islem") == "kaldir":
        foto.kaldir(p)
        messages.success(request, "Fotoğraf kaldırıldı.")
    elif not request.FILES.get("fotograf"):
        messages.error(request, "Fotoğraf seçin.")
    else:
        try:
            foto.kaydet(p, request.FILES["fotograf"].read())
        except foto.FotoHatasi as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Fotoğraf güncellendi.")
    return redirect("personel:detay", pk=p.pk)


# ---------------------------------------------------------------- kart alanları (yönetici)

@yetki_gerekli(BIRIM, YONETIM)
def alanlar(request):
    duzenlenen = KartAlani.objects.filter(pk=request.GET.get("duzenle") or 0).first()
    form = KartAlaniFormu(instance=duzenlenen)
    if request.method == "POST":
        if request.POST.get("islem") == "sil":
            a = get_object_or_404(KartAlani, pk=request.POST.get("pk") or 0)
            dolu = a.degerler.exclude(deger="").count()
            if dolu:
                messages.error(request, f"“{a.ad}” {dolu} personelde dolu; silmek yerine “kullanımda” işaretini "
                                        "kaldırın (bilgiler korunur).")
            else:
                a.delete()
                messages.success(request, f"“{a.ad}” silindi.")
            return redirect("personel:alanlar")
        duzenlenen = KartAlani.objects.filter(pk=request.POST.get("pk") or 0).first()
        form = KartAlaniFormu(request.POST, instance=duzenlenen)
        if form.is_valid():
            a = form.save()
            messages.success(request, f"“{a.ad}” kaydedildi.")
            return redirect("personel:alanlar")
    return render(request, "personel/alanlar.html", _baglam(
        request, form=form, duzenlenen=duzenlenen, sekme="alanlar", breadcrumb_ek=True,
        alanlar=KartAlani.objects.annotate(dolu=Count("degerler", filter=~Q(degerler__deger="")))))


# ---------------------------------------------------------------- teşkilat şeması

@yetki_gerekli(BIRIM)
def teskilat(request):
    return render(request, "personel/teskilat.html", _baglam(
        request, kokler=kart.agac(), sekme="teskilat", breadcrumb_ek=True,
        bos=not TeskilatBirimi.objects.exists()))


@yetki_gerekli(BIRIM)
def teskilat_birimi(request, pk):
    b = get_object_or_404(TeskilatBirimi.objects.select_related("ust", "bolum__baskan"), pk=pk)
    yonetici = _yonetici(request)
    if request.method == "POST":
        if not yonetici:
            raise PermissionDenied
        islem = request.POST.get("islem")
        if islem == "ata":
            ids = [int(x) for x in request.POST.getlist("personel") if x.isdigit()]
            gorev = request.POST.get("gorev_unvani", "").strip()[:80]
            for p in Personel.objects.filter(pk__in=ids):
                p.teskilat_birimi = b
                if gorev:
                    p.gorev_unvani = gorev
                p.save(update_fields=["teskilat_birimi", "gorev_unvani", "guncelleme"])
            messages.success(request, f"{len(ids)} personel {b.ad} birimine atandı.")
        elif islem == "cikar":
            p = get_object_or_404(Personel, pk=request.POST.get("pk") or 0, teskilat_birimi=b)
            p.teskilat_birimi = None
            p.save(update_fields=["teskilat_birimi", "guncelleme"])
            messages.success(request, f"{p.ad_soyad} birimden çıkarıldı.")
        elif islem == "gorev":
            p = get_object_or_404(Personel, pk=request.POST.get("pk") or 0)
            p.gorev_unvani = request.POST.get("gorev_unvani", "").strip()[:80]
            p.idari_kadro = request.POST.get("idari_kadro") == "1"
            p.save(update_fields=["gorev_unvani", "idari_kadro", "guncelleme"])
            messages.success(request, f"{p.ad_soyad}: görev bilgisi kaydedildi.")
        elif islem == "alt_birim":
            ad = request.POST.get("ad", "").strip()[:120]
            if ad:
                TeskilatBirimi.objects.create(ad=ad, ust=b, tur=request.POST.get("tur") or TeskilatBirimi.KISIM,
                                              sira=b.altlar.count() * 10 + 10)
                messages.success(request, f"“{ad}” eklendi.")
        elif islem == "duzenle":
            form = TeskilatFormu(request.POST, instance=b)
            if form.is_valid():
                form.save()
                messages.success(request, "Birim kaydedildi.")
            else:
                messages.error(request, " ".join(e for es in form.errors.values() for e in es))
        elif islem == "sil":
            if b.altlar.exists() or b.personeller.exists():
                messages.error(request, "Alt birimi ya da personeli olan birim silinemez; önce boşaltın.")
            else:
                ust = b.ust
                try:
                    b.delete()
                except ProtectedError:
                    messages.error(request, "Birim silinemedi.")
                else:
                    messages.success(request, "Birim silindi.")
                    return redirect("personel:teskilat_birimi", pk=ust.pk) if ust else redirect("personel:teskilat")
        return redirect("personel:teskilat_birimi", pk=b.pk)
    kisiler = list(kart.birim_personeli(b))
    if request.yetki_kapsam == Yetki.BOLUM:
        kisiler = [p for p in kisiler if p.bolum_id == request.user.bolum_id]
    zincir, u = [], b.ust
    while u is not None and len(zincir) < 10:
        zincir.append(u)
        u = u.ust
    return render(request, "personel/teskilat_birimi.html", _baglam(
        request, b=b, kisiler=kisiler, zincir=list(reversed(zincir)), sekme="teskilat", breadcrumb_ek=True,
        altlar=b.altlar.filter(aktif=True).order_by("sira", "ad"), turler=TeskilatBirimi.TURLER,
        form=TeskilatFormu(instance=b) if yonetici else None,
        adaylar=Personel.objects.filter(aktif=True).exclude(teskilat_birimi=b).select_related("bolum", "rutbe")
        .order_by("ad_soyad") if yonetici else []))
