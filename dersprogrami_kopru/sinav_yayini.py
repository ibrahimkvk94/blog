"""Yayınlanan sınav programları (KAMYOSİS sayfaları).

Sınav Planları biriminde:
- Görüntüleme (bölümler): yalnızca yayınlanan dönemlerin takvimi, sınıfların programı, görevlendirmeler ve salonlar.
- Düzenleme ve üstü (sınav planlamacısı): tüm dönemler (yayında olmayanlar önizleme olarak), yayınla / yayından kaldır.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.yetki import DUZENLEME, yetki_gerekli
from personel.models import Bolum

from .models import SinavYayini
from .yetki import SINAV_BIRIMI, sinav_planlamacisi

GORUNUMLER = [("takvim", "Takvim", "calendar3"), ("siniflar", "Sınıflar", "people"),
              ("gorevler", "Görevlendirmeler", "person-badge"), ("salonlar", "Salonlar", "door-open")]


def _donemler(request):
    from sinav.models import ExamPeriod

    qs = ExamPeriod.objects.select_related("school", "kamyosis_yayini__yayinlayan").order_by("-start_date", "-pk")
    return qs if sinav_planlamacisi(request.user) else qs.filter(kamyosis_yayini__isnull=False)


def _donem(request, pk):
    d = _donemler(request).filter(pk=pk).first()
    if d is None:
        raise Http404("Bu sınav programı yayında değil.")
    return d


def _yayin(d):
    try:
        return d.kamyosis_yayini
    except SinavYayini.DoesNotExist:
        return None


@yetki_gerekli(SINAV_BIRIMI)
def liste(request):
    from sinav import services as sinavlar

    planlamaci = sinav_planlamacisi(request.user)
    satirlar = []
    for d in _donemler(request):
        satirlar.append({"donem": d, "yayin": _yayin(d), "sinav": d.exams.filter(excluded=False).count(),
                         "yerlesen": len(sinavlar.placements(d)) if planlamaci else None})
    return render(request, "dersprogrami_kopru/sinav_programi.html", {
        "satirlar": satirlar, "planlamaci": planlamaci, "breadcrumb_ek": False})


def _bolum_kodu(request):
    """Görevlendirmelerde süzülecek bölüm: ?bolum=KOD; verilmezse bölüm hesabında kendi bölümü, "hepsi" = süzme yok."""
    secim = request.GET.get("bolum")
    if secim == "hepsi":
        return ""
    if secim:
        return secim
    bolum = getattr(request.user, "bolum", None)
    return (bolum.kod or "") if bolum is not None and not sinav_planlamacisi(request.user) else ""


@yetki_gerekli(SINAV_BIRIMI)
def donem(request, pk):
    from sinav import services as sinavlar

    d = _donem(request, pk)
    gorunum = request.GET.get("gorunum", "takvim")
    if gorunum not in {g for g, _a, _i in GORUNUMLER}:
        gorunum = "takvim"
    satirlar = sinavlar.placements(d)
    ctx = {"d": d, "yayin": _yayin(d), "planlamaci": sinav_planlamacisi(request.user), "gorunum": gorunum,
           "gorunumler": GORUNUMLER, "oturumlar": d.session_times, "yerlesen": len(satirlar), "breadcrumb_ek": True}
    if gorunum == "takvim":
        ctx["takvim"] = [g for g in sinavlar.calendar(d, satirlar) if any(g["cells"])]
    elif gorunum == "siniflar":
        ctx["siniflar"] = sinavlar.by_class(d, satirlar)
    elif gorunum == "gorevler":
        kod = _bolum_kodu(request)
        gorevliler = sinavlar.by_teacher(d, satirlar)
        adlar = dict(Bolum.objects.exclude(kod=None).values_list("kod", "ad"))
        ctx["bolumler"] = sorted({(t.department, adlar.get(t.department, t.department)) for t, _g in gorevliler
                                  if t.department}, key=lambda b: b[1])
        ctx["secili_bolum"] = kod
        ctx["gorevliler"] = [(t, g, adlar.get(t.department, t.department)) for t, g in gorevliler
                             if not kod or t.department == kod]
        ctx["toplam_gorevli"] = len(gorevliler)
    else:
        ctx["salonlar"] = sinavlar.by_room(d, satirlar)
    return render(request, "dersprogrami_kopru/sinav_donemi.html", ctx)


@yetki_gerekli(SINAV_BIRIMI)
def excel(request, pk):
    from sinav import excel as sinav_excel

    d = _donem(request, pk)
    cevap = HttpResponse(sinav_excel.build(d),
                         content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    cevap["Content-Disposition"] = f'attachment; filename="sinav-programi-{d.pk}.xlsx"'
    return cevap


@require_POST
@yetki_gerekli(SINAV_BIRIMI, DUZENLEME)
def yayin(request, pk):
    from sinav.models import ExamPeriod

    d = get_object_or_404(ExamPeriod, pk=pk)
    if request.POST.get("islem") == "kaldir":
        SinavYayini.objects.filter(donem=d).delete()
        messages.success(request, f"“{d.name}” yayından kaldırıldı; bölümler artık görmüyor.")
    else:
        if d.is_running:
            messages.error(request, "Program şu anda oluşturuluyor; bitince yayınlayın.")
            return redirect("dersprogrami_kopru:sinav_programi")
        SinavYayini.objects.update_or_create(donem=d, defaults={"yayinlayan": request.user, "zaman": timezone.now()})
        messages.success(request, f"“{d.name}” yayınlandı: bölümler sınav programını ve görevlendirmeleri görebilir.")
    return redirect(request.POST.get("geri") or "dersprogrami_kopru:sinav_programi")
