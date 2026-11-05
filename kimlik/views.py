"""Kimlik Kartı Okuma.

Telefonla çekilen T.C. kimlik kartı fotoğrafları bu bilgisayardaki yazı okuma motoruyla okunur (fotoğraf saklanmaz,
internete gönderilmez), okunan bilgiler bir çalışma listesine yazılır. Liste Excel'e alınır, "Tür" sütununda
Personel / Öğrenci seçilip geri yüklenir; seçilenler personel kartlarına ya da öğrenci kaydına aktarılır.

Yetki: listeyi kullanmak için "Kimlik Kartı Okuma" biriminde düzenleme. Aktarmak için ayrıca Personel Kartları
(personel satırları) ya da Öğrenci Kaydı (öğrenci satırları) biriminde yönetim.
"""

import datetime

from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from PIL import UnidentifiedImageError

from core.yetki import DUZENLEME, YONETIM, birim_bul, etkin_yetki, yetki_gerekli, yol

from . import aktarim, excel, motor, servis
from .forms import KimlikFormu
from .models import KimlikKaydi

BIRIM = "kimlik-okuma"
EN_BUYUK_FOTO = 20 * 1024 * 1024
EN_BUYUK_KARE = 3 * 1024 * 1024


def _seviye(request, slug):
    try:
        return etkin_yetki(request, birim_bul(request, slug))[0]
    except Http404:
        return 0


def _aktarim_yetkileri(request):
    return {"personel_yetkisi": _seviye(request, "personel-bilgileri") >= YONETIM,
            "ogrenci_yetkisi": _seviye(request, "ogrenci-kaydi") >= YONETIM}


def _baglam(request, **ek):
    return {"yol": yol(request, request.birim), **ek}


@yetki_gerekli(BIRIM, DUZENLEME)
def liste(request):
    goster = "aktarilan" if request.GET.get("goster") == "aktarilan" else "bekleyen"
    tum = KimlikKaydi.objects.all()
    bekleyen = tum.filter(aktarim__isnull=True)
    aktarilan = tum.filter(aktarim__isnull=False)
    kayitlar = list((aktarilan.order_by("-aktarim", "-id") if goster == "aktarilan" else bekleyen))
    hazir, motor_aciklama = motor.durum()
    return render(request, "kimlik/liste.html", _baglam(
        request, kayitlar=kayitlar, goster=goster, bekleyen_sayisi=bekleyen.count(),
        aktarilan_sayisi=aktarilan.count(), hazir_sayisi=bekleyen.exclude(tur="").count(),
        motor_hazir=hazir, motor_aciklama=motor_aciklama, turler=KimlikKaydi.TURLER,
        yonetici=request.yetki_seviye >= YONETIM or request.user.is_superuser, **_aktarim_yetkileri(request)))


def _cevap(request, hata=None, adres=None):
    """Sayfa içinden (fetch) gelen isteğe JSON, düz form gönderimine yönlendirme."""
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"hata": hata} if hata else {"yonlendir": adres}, status=400 if hata else 200)
    if hata:
        messages.error(request, hata)
    return redirect(adres or "kimlik:liste")


@require_POST
@yetki_gerekli(BIRIM, DUZENLEME)
def oku(request):
    on, arka = request.FILES.get("on"), request.FILES.get("arka")
    if not on and not arka:
        return _cevap(request, "Kartın ön ve/veya arka yüzünün fotoğrafını seçin.")
    if any(f and f.size > EN_BUYUK_FOTO for f in (on, arka)):
        return _cevap(request, "Fotoğraf 20 MB'tan büyük olamaz.")
    try:
        with motor.sira(bekleme=60):
            sonuc = motor.oku(on, arka)
    except motor.Mesgul:
        return _cevap(request, "Okuma sunucusu şu an yoğun; biraz sonra yeniden deneyin.")
    except motor.MotorYok as e:
        return _cevap(request, f"{e} Sistem yöneticisine bildirin.")
    except (UnidentifiedImageError, OSError, ValueError):
        return _cevap(request, "Fotoğraf açılamadı. Telefonun kamerasıyla JPEG / PNG olarak çekip yeniden deneyin.")
    k = servis.sonuctan_kayit(sonuc, request.user)
    tur = request.POST.get("tur", "")
    if tur in dict(KimlikKaydi.TURLER):
        k.tur = tur
        k.save(update_fields=["tur"])
    return _cevap(request, adres=reverse("kimlik:duzenle", args=[k.pk]) + "?yeni=1")


@require_POST
@yetki_gerekli(BIRIM, DUZENLEME)
def kare(request):
    """Canlı kameradan gelen tek kare: okunmaya hazır mı? {"uygun": bool, "mesaj": str}. Kare saklanmaz."""
    dosya, yuz = request.FILES.get("kare"), request.POST.get("yuz", "on")
    if not dosya or dosya.size > EN_BUYUK_KARE:
        return JsonResponse({"uygun": False, "mesaj": "Kare alınamadı."}, status=400)
    try:
        with motor.sira(bekleme=3):
            uygun, mesaj = motor.hizli_kontrol(dosya, "arka" if yuz == "arka" else "on")
    except motor.Mesgul:
        return JsonResponse({"uygun": False, "mesaj": "Sunucu başka bir kartı okuyor, bekleniyor…"})
    except motor.MotorYok as e:
        return JsonResponse({"uygun": False, "mesaj": str(e), "dur": True}, status=503)
    except (UnidentifiedImageError, OSError, ValueError):
        return JsonResponse({"uygun": False, "mesaj": "Kare okunamadı."})
    return JsonResponse({"uygun": uygun, "mesaj": mesaj})


@yetki_gerekli(BIRIM, DUZENLEME)
def duzenle(request, pk):
    k = get_object_or_404(KimlikKaydi, pk=pk, aktarim__isnull=True)
    supheli = k.supheli_alanlar
    if request.method == "POST":
        if request.POST.get("islem") == "sil":
            k.delete()
            messages.success(request, "Satır silindi.")
            return redirect("kimlik:liste")
        form = KimlikFormu(request.POST, instance=k, supheli=supheli)
        if form.is_valid():
            k = form.save(commit=False)
            servis.denetle(k).save()
            messages.success(request, f"{k.ad_soyad or 'Satır'} kaydedildi.")
            if "sonraki" in request.POST:
                return redirect(reverse("kimlik:liste") + "#oku")
            return redirect("kimlik:liste")
    else:
        form = KimlikFormu(instance=k, supheli=supheli)
    return render(request, "kimlik/duzenle.html", _baglam(
        request, k=k, form=form, supheli=supheli, yeni=request.GET.get("yeni") == "1", breadcrumb_ek=True))


@require_POST
@yetki_gerekli(BIRIM, DUZENLEME)
def toplu(request):
    idler = [i for i in request.POST.getlist("k") if i.isdigit()]
    islem = request.POST.get("islem", "")
    if not idler:
        messages.warning(request, "Önce satır seçin.")
        return redirect("kimlik:liste")
    qs = KimlikKaydi.objects.filter(pk__in=idler, aktarim__isnull=True)
    if islem == "aktar":
        return redirect(reverse("kimlik:aktar") + "?" + "&".join(f"k={i}" for i in idler))
    if islem in dict(KimlikKaydi.TURLER) or islem == "tursuz":
        n = qs.update(tur="" if islem == "tursuz" else islem)
        messages.success(request, f"{n} satırın türü değiştirildi.")
    elif islem == "sil":
        n = qs.delete()[0]
        messages.success(request, f"{n} satır silindi.")
    return redirect("kimlik:liste")


@yetki_gerekli(BIRIM, DUZENLEME)
def aktar(request):
    yetkiler = _aktarim_yetkileri(request)
    kaynak = request.POST if request.method == "POST" else request.GET
    idler = [i for i in kaynak.getlist("k") if i.isdigit()]
    if idler or request.method == "POST":  # onayda yalnız önizlemede gösterilen satırlar
        kayitlar = list(KimlikKaydi.objects.filter(pk__in=idler).order_by("id"))
    else:  # "Aktarıma geç": türü seçilmiş tüm bekleyen satırlar
        kayitlar = list(KimlikKaydi.objects.filter(aktarim__isnull=True).exclude(tur="").order_by("id"))
    planlar = aktarim.planla(kayitlar, **yetkiler)
    if request.method == "POST":
        sayac = aktarim.uygula(planlar)
        if sayac["personel"] or sayac["ogrenci"]:
            messages.success(request, f"Aktarıldı: {sayac['personel']} personel kartı, {sayac['ogrenci']} öğrenci "
                                      f"kaydı ({sayac['yeni']} yeni).")
        else:
            messages.warning(request, "Aktarılacak satır yok.")
        return redirect(reverse("kimlik:liste") + "?goster=aktarilan")
    return render(request, "kimlik/aktar.html", _baglam(
        request, planlar=planlar, aktarilacak=[p for p in planlar if p.aktarilir], breadcrumb_ek=True, **yetkiler))


@yetki_gerekli(BIRIM, DUZENLEME)
def excel_indir(request):
    kayitlar = list(KimlikKaydi.objects.filter(aktarim__isnull=True).order_by("id"))
    cevap = HttpResponse(excel.yaz(kayitlar),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    cevap["Content-Disposition"] = f'attachment; filename="kimlik_okuma_{datetime.date.today():%Y%m%d}.xlsx"'
    return cevap


@require_POST
@yetki_gerekli(BIRIM, DUZENLEME)
def excel_yukle(request):
    dosya = request.FILES.get("dosya")
    if not dosya:
        messages.error(request, "Excel dosyasını seçin.")
        return redirect("kimlik:liste")
    try:
        guncellenen, eklenen = excel.ice_aktar(dosya, request.user)
    except excel.ExcelHatasi as e:
        messages.error(request, str(e))
        return redirect("kimlik:liste")
    hazir = KimlikKaydi.objects.filter(aktarim__isnull=True).exclude(tur="").count()
    messages.success(request, f"Excel işlendi: {guncellenen} satır güncellendi, {eklenen} satır eklendi. Türü seçilmiş "
                              f"{hazir} satır aktarıma hazır.")
    return redirect("kimlik:liste")


@require_POST
@yetki_gerekli(BIRIM, DUZENLEME)
def aktarilanlari_sil(request):
    n = KimlikKaydi.objects.filter(aktarim__isnull=False).delete()[0]
    messages.success(request, f"Aktarılmış {n} satır listeden silindi (personel / öğrenci kayıtları yerinde kalır).")
    return redirect("kimlik:liste")
