"""Sınav takvimi sayfaları.

Yayınlanan planları giriş yapan herkes görür. Plan yükleme (Excel), ad değiştirme, yayınlama / yayından kaldırma ve
silme Sınav İcrası biriminde Düzenleme yetkisi ister; yayında olmayan planları da yalnız onlar görür (önizleme).
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
import json

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bildirim import servis as bildirim_servisi
from personel.models import Bolum

from . import servis
from .models import Takvim
from .servis import TakvimHatasi

EN_BUYUK_DOSYA = 5 * 1024 * 1024
# Sınav İcrası sayfasının sekmeleri (kod, ad, ikon, adres adı); yeni sekmeler buraya eklenir.
SEKMELER = [("takvim", "Sınav Takvimi", "calendar2-week", "sinavtakvimi:liste"),
            ("malzeme", "Sınav Malzemeleri", "calculator", "sinavtakvimi:malzemeler")]


def _baglam(request, **ctx):
    ctx.setdefault("duzenleyebilir", servis.duzenleyebilir(request))
    ctx.setdefault("sekmeler", SEKMELER)
    ctx.setdefault("sekme", "takvim")
    try:
        from core.yetki import birim_bul, yol

        request.birim = birim_bul(request, servis.BIRIM)
        ctx.setdefault("yol", yol(request, request.birim))
    except Http404:
        pass
    return ctx


def _yetkili(request):
    if not servis.duzenleyebilir(request):
        raise PermissionDenied("Sınav planı yüklemek ve yayınlamak için Sınav İcrası biriminde Düzenleme yetkisi gerekir.")


def _takvim(request, pk):
    t = get_object_or_404(Takvim, pk=pk)
    if not t.yayinda and not servis.duzenleyebilir(request):
        raise Http404("Bu sınav planı yayında değil.")
    return t


def liste(request):
    duz = servis.duzenleyebilir(request)
    qs = Takvim.objects.all() if duz else Takvim.objects.filter(yayinda=True)
    takvimler = list(qs)
    if not duz and len(takvimler) == 1:
        return redirect("sinavtakvimi:takvim", takvimler[0].pk)
    satirlar = [{"t": t, "ozet": servis.ozet(t)} for t in takvimler]
    return render(request, "sinavtakvimi/liste.html", _baglam(request, satirlar=satirlar, duzenleyebilir=duz))


def takvim(request, pk):
    t = _takvim(request, pk)
    adlar = dict(Bolum.objects.exclude(kod=None).values_list("kod", "ad"))
    veri = servis.sayfa_verisi(t, adlar)
    benim = getattr(getattr(request.user, "bolum", None), "kod", None)
    return render(request, "sinavtakvimi/takvim.html", _baglam(
        request, t=t, ozet=servis.ozet(t), benim_bolum=benim if benim in {p["kod"] for p in veri["programlar"]} else "",
        breadcrumb_ek=True, **veri))


def excel(request, pk):
    t = _takvim(request, pk)
    cevap = HttpResponse(servis.excel_yaz(t),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    cevap["Content-Disposition"] = f'attachment; filename="sinav-plani-{t.pk}.xlsx"'
    return cevap


def yukle(request):
    """Excel'den yeni plan ya da var olan planın satırlarını yenileme."""
    _yetkili(request)
    hedef = None
    if request.GET.get("takvim") or request.POST.get("takvim"):
        hedef = get_object_or_404(Takvim, pk=request.GET.get("takvim") or request.POST.get("takvim"))
    if request.method == "POST":
        dosya = request.FILES.get("dosya")
        if dosya is None:
            messages.error(request, "Excel dosyası seçin.")
        elif dosya.size > EN_BUYUK_DOSYA:
            messages.error(request, "Dosya 5 MB'tan büyük olamaz.")
        else:
            try:
                ad, satirlar, uyarilar = servis.excel_oku(dosya)
            except TakvimHatasi as e:
                messages.error(request, str(e))
            else:
                ad = (request.POST.get("ad") or "").strip() or (hedef.ad if hedef else "") or ad or "Sınav planı"
                if hedef is None:
                    hedef = Takvim.objects.create(ad=ad[:200], olusturan=request.user)
                else:
                    hedef.ad = ad[:200]
                    hedef.save(update_fields=["ad"])
                servis.satirlari_yaz(hedef, satirlar)
                messages.success(request, f"{len(satirlar)} satır okundu." + (
                    " Yayında: değişiklik herkese hemen yansıdı." if hedef.yayinda else
                    " Kontrol edip “Yayınla”ya basınca herkes görür."))
                for u in uyarilar[:10]:
                    messages.warning(request, u)
                if len(uyarilar) > 10:
                    messages.warning(request, f"… ve {len(uyarilar) - 10} uyarı daha.")
                return redirect("sinavtakvimi:takvim", hedef.pk)
    return render(request, "sinavtakvimi/yukle.html", _baglam(request, hedef=hedef, breadcrumb_ek=True))


@require_POST
def duzenle(request, pk):
    _yetkili(request)
    t = get_object_or_404(Takvim, pk=pk)
    ad = (request.POST.get("ad") or "").strip()
    if ad:
        t.ad = ad[:200]
    t.aciklama = (request.POST.get("aciklama") or "").strip()[:300]
    t.save(update_fields=["ad", "aciklama", "guncelleme"])
    messages.success(request, "Kaydedildi.")
    return redirect("sinavtakvimi:takvim", t.pk)


@require_POST
def yayin(request, pk):
    _yetkili(request)
    t = get_object_or_404(Takvim, pk=pk)
    if request.POST.get("islem") == "kaldir":
        t.yayinda = False
        t.save(update_fields=["yayinda", "guncelleme"])
        messages.success(request, f"“{t.ad}” yayından kaldırıldı.")
    else:
        if not t.satirlar.exists():
            messages.error(request, "Planda satır yok; önce Excel yükleyin.")
            return redirect("sinavtakvimi:takvim", t.pk)
        t.yayinda, t.yayin_zamani, t.yayinlayan = True, timezone.now(), request.user
        t.save(update_fields=["yayinda", "yayin_zamani", "yayinlayan", "guncelleme"])
        sayi = bildirim_servisi.sinav_takvimi(t, request.user) if request.POST.get("bildir") else 0
        messages.success(request, f"“{t.ad}” yayınlandı: giriş yapan herkes görebilir."
                         + (f" {sayi} kişiye bildirim gitti." if sayi else ""))
    return redirect("sinavtakvimi:takvim", t.pk)


@require_POST
def sil(request, pk):
    _yetkili(request)
    t = get_object_or_404(Takvim, pk=pk)
    if t.yayinda:
        messages.error(request, "Yayındaki plan silinemez; önce yayından kaldırın.")
        return redirect("sinavtakvimi:takvim", t.pk)
    ad = t.ad
    t.delete()
    messages.success(request, f"“{ad}” silindi.")
    return redirect("sinavtakvimi:liste")


# ---------------------------------------------------------------- sınav malzemeleri

def malzemeler(request, pk=None):
    """Yayındaki planın ders × program satırları ve sınavda kullanılacak malzeme. Herkes görür; bölümler kendi
    satırlarını (programı ya da dersi kendi bölümünün olan) girer, Sınav İcrası yetkilileri hepsini."""
    duz = servis.duzenleyebilir(request)
    qs = Takvim.objects.all() if duz else Takvim.objects.filter(yayinda=True)
    takvimler = list(qs.order_by("-yayinda", "-olusturma"))
    if pk is not None:
        t = _takvim(request, pk)
    elif takvimler:
        t = takvimler[0]
    else:
        return render(request, "sinavtakvimi/malzemeler.html", _baglam(request, sekme="malzeme", t=None))
    yetki = servis.MalzemeYetkisi(request)
    satirlar = servis.malzeme_satirlari(t, yetki)
    programlar = sorted({r["bolum"] for r in satirlar if r["bolum"]}, key=servis.tr_anahtar)
    ders_bolumleri = sorted({(r["ders_bolumu"], r["ders_bolumu_adi"]) for r in satirlar}, key=lambda x: servis.tr_anahtar(x[1]))
    adlar = {r["bolum"]: r["bolum_adi"] for r in satirlar}
    ilerleme = []
    for p in programlar:
        rs = [r for r in satirlar if r["bolum"] == p]
        ilerleme.append({"kod": p, "ad": adlar.get(p, p), "toplam": len(rs), "girilen": sum(r["girildi"] for r in rs)})
    benim = yetki.bolum.kod if yetki.bolum is not None and yetki.bolum.kod else ""
    return render(request, "sinavtakvimi/malzemeler.html", _baglam(
        request, sekme="malzeme", t=t, takvimler=takvimler, satirlar=satirlar, programlar=programlar,
        ders_bolumleri=ders_bolumleri, ilerleme=ilerleme, malzeme_secenekleri=servis.MALZEMELER, benim=benim,
        benim_program=benim in programlar, girebilen=sum(r["girebilir"] for r in satirlar),
        girilen=sum(r["girildi"] for r in satirlar), yetki=yetki, breadcrumb_ek=True))


@require_POST
def malzeme_kaydet(request, pk):
    t = _takvim(request, pk)
    try:
        veri = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"hata": "Geçersiz istek."}, status=400)
    kod, bolum = str(veri.get("kod") or ""), str(veri.get("bolum") or "")
    yetki = servis.MalzemeYetkisi(request)
    satirlar = {(r["kod"], r["bolum"]): r for r in servis.malzeme_satirlari(t, yetki)}
    hedefler = [satirlar.get((kod, bolum))]
    if hedefler[0] is None:
        return JsonResponse({"hata": "Bu ders planda yok."}, status=404)
    if veri.get("hepsi"):  # aynı dersin (kodun) girebildiği tüm programları
        hedefler = [r for (k, _b), r in satirlar.items() if k == kod]
    hedefler = [r for r in hedefler if r["girebilir"]]
    if not hedefler:
        return JsonResponse({"hata": "Bu satırı yalnız ilgili bölüm ya da Sınav İcrası yetkilisi girebilir."}, status=403)
    sonuc = []
    for r in hedefler:
        m = servis.malzeme_kaydet(t, r["kod"], r["bolum"], veri.get("secimler") or [], veri.get("diger"),
                                  bool(veri.get("yok")), request.user)
        sonuc.append({"bolum": r["bolum"], "metin": servis.malzeme_metni(m),
                      "secimler": m.secimler.split(",") if m and m.secimler else [], "diger": m.diger if m else "",
                      "yok": bool(m and m.yok)})
    return JsonResponse({"tamam": True, "satirlar": sonuc})


def malzeme_excel(request, pk):
    t = _takvim(request, pk)
    satirlar = servis.malzeme_satirlari(t)
    program = request.GET.get("program")
    if program:
        satirlar = [r for r in satirlar if r["bolum"] == program]
    cevap = HttpResponse(servis.malzeme_excel(t, satirlar),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    cevap["Content-Disposition"] = f'attachment; filename="sinav-malzemeleri-{t.pk}.xlsx"'
    return cevap
