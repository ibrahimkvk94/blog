import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum, Personel

from . import servis
from .models import ROLLER, IslenenDonem, SinavGorevi


def _baglam(request, **ek):
    request.birim = birim_bul(request, servis.BIRIM)
    return {"yol": yol(request, request.birim), "y": servis.yetki(request), **ek}


def _yil(request):
    try:
        return servis.yil_baslangici(datetime.date(int(request.GET.get("yil")), 10, 1))
    except (TypeError, ValueError):
        return servis.yil_baslangici(timezone.localdate())


def _okullar():
    from timetable.models import School

    return list(School.objects.order_by("-id"))


def _varsayilan_okul(okullar):
    """Ders saati için: en son sınav döneminin programı, yoksa en son program."""
    from sinav.models import ExamPeriod

    son = ExamPeriod.objects.order_by("-start_date", "-id").values_list("school_id", flat=True).first()
    return next((o for o in okullar if o.pk == son), okullar[0] if okullar else None)


def _yonetim(request):
    y = servis.yetki(request)
    if not y.yonetim or y.kapsam_bolum is not None:
        raise PermissionDenied
    return y


@login_required
def puantaj(request):
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    bas = _yil(request)
    okullar = _okullar()
    okul = next((o for o in okullar if str(o.pk) == request.GET.get("okul")), None) or _varsayilan_okul(okullar)
    bolum = y.kapsam_bolum
    if bolum is None and request.GET.get("bolum", "").isdigit():
        bolum = Bolum.objects.filter(pk=request.GET["bolum"]).first()
    satirlar, istatistik = servis.tablo(bas, okul, bolum)
    if request.GET.get("indir"):
        return _excel(bas, okul, satirlar, istatistik)
    bu_yil = servis.yil_baslangici(timezone.localdate())
    yillar = sorted({servis.yil_baslangici(t) for t in SinavGorevi.objects.dates("tarih", "month")} | {bu_yil}, reverse=True)
    donemler = []
    if y.yonetim and y.kapsam_bolum is None:
        from sinav.models import ExamPeriod, ExamRoom

        islenen = {i.sinav_donemi_id: i for i in IslenenDonem.objects.select_related("isleyen")}
        for p in ExamPeriod.objects.select_related("school").order_by("-start_date"):
            if servis.yil_baslangici(p.start_date) == bas:
                gorev = ExamRoom.proctors.through.objects.filter(examroom__placement__exam__period=p).count()
                donemler.append({"donem": p, "islenen": islenen.get(p.pk), "gorev": gorev})
    elle = SinavGorevi.objects.filter(elle=True, tarih__range=(bas, servis.yil_sonu(bas))).select_related("personel")
    if bolum is not None:
        elle = elle.filter(personel__bolum=bolum)
    return render(request, "sinavgorev/puantaj.html", _baglam(
        request, bas=bas, yil=servis.yil_etiketi(bas), yillar=[(b.year, servis.yil_etiketi(b)) for b in yillar],
        okullar=okullar, okul=okul, satirlar=satirlar, ist=istatistik, donemler=donemler, elle=list(elle),
        bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [], secili_bolum=bolum,
        roller=ROLLER, personeller=Personel.objects.filter(aktif=True).order_by("ad_soyad") if y.yonetim else [],
        bugun=timezone.localdate(),
    ))


@login_required
def personel(request, pk):
    y = servis.yetki(request)
    p = get_object_or_404(Personel.objects.select_related("bolum"), pk=pk)
    if not y.goruntule or (y.kapsam_bolum is not None and p.bolum_id != y.kapsam_bolum.pk):
        raise PermissionDenied
    bas = _yil(request)
    gorevler = list(p.sinav_gorevleri.filter(tarih__range=(bas, servis.yil_sonu(bas))).order_by("tarih", "saat"))
    return render(request, "sinavgorev/personel.html", _baglam(
        request, p=p, bas=bas, yil=servis.yil_etiketi(bas), gorevler=gorevler,
        puan=sum(g.puan for g in gorevler), geri=f"{reverse('sinavgorev:puantaj')}?yil={bas.year}"))


@require_POST
@login_required
def isle(request, period_pk):
    _yonetim(request)
    from sinav import services as sinav_servis
    from sinav.models import ExamPeriod

    period = get_object_or_404(ExamPeriod, pk=period_pk)
    if request.POST.get("islem") == "geri":
        n = servis.geri_al(period)
        messages.success(request, f"“{period.name}” puantajdan çıkarıldı ({n} görev silindi).")
    else:
        n, eslesmeyen = servis.isle(period, request.user)
        messages.success(request, f"“{period.name}” puantaja işlendi: {n} görev.")
        if eslesmeyen:
            messages.warning(request, f"{len(eslesmeyen)} öğretmen KAMYOSİS personeliyle eşleşmedi, görevleri işlenmedi: "
                                      + ", ".join(eslesmeyen[:15]) + (" …" if len(eslesmeyen) > 15 else ""))
        sorun = [i for i in sinav_servis.validate(period) if i["level"] == "error"]
        if sorun:
            messages.warning(request, f"Sınav programında {len(sorun)} kural hatası var (Sınav Planlama → Sonuçlar); "
                                      "düzeltince dönemi yeniden işleyin.")
    return redirect(f"{reverse('sinavgorev:puantaj')}?yil={servis.yil_baslangici(period.start_date).year}")


@require_POST
@login_required
def elle_ekle(request):
    _yonetim(request)
    p = get_object_or_404(Personel, pk=request.POST.get("personel") or 0, aktif=True)
    try:
        tarih = datetime.date.fromisoformat(request.POST.get("tarih", ""))
    except ValueError:
        messages.error(request, "Tarih seçin.")
        return redirect("sinavgorev:puantaj")
    rol = request.POST.get("rol") if request.POST.get("rol") in dict(ROLLER) else "G"
    adet = max(1, min(20, int(request.POST.get("adet") or 1) if (request.POST.get("adet") or "1").isdigit() else 1))
    for _ in range(adet):
        SinavGorevi.objects.create(personel=p, tarih=tarih, saat=(request.POST.get("saat") or "")[:5], rol=rol, elle=True,
                                   aciklama=(request.POST.get("aciklama") or "").strip()[:200], ekleyen=request.user)
    messages.success(request, f"{p.ad_soyad}: {adet} görev eklendi ({tarih:%d.%m.%Y}).")
    return redirect(f"{reverse('sinavgorev:puantaj')}?yil={servis.yil_baslangici(tarih).year}")


@require_POST
@login_required
def elle_sil(request, pk):
    _yonetim(request)
    g = get_object_or_404(SinavGorevi, pk=pk, elle=True)
    g.delete()
    messages.success(request, "Elle eklenen görev silindi.")
    return redirect(f"{reverse('sinavgorev:puantaj')}?yil={servis.yil_baslangici(g.tarih).year}")


@require_POST
@login_required
def roller(request):
    _yonetim(request)
    degisen = 0
    for p in Personel.objects.filter(pk__in=[int(x) for x in request.POST.getlist("p") if x.isdigit()]):
        yeni = "".join(r for r, _ in ROLLER if request.POST.get(f"rol-{p.pk}-{r}"))
        if yeni != p.sinav_rolleri:
            p.sinav_rolleri = yeni
            p.save(update_fields=["sinav_rolleri"])
            degisen += 1
    if degisen:
        servis.rolleri_esitle()
    if request.headers.get("x-requested-with") == "fetch":  # kutuya tıklanınca anında kayıt
        return JsonResponse({"ok": True, "degisen": degisen})
    messages.success(request, f"Görev rolleri kaydedildi ({degisen} personel değişti).")
    geri = request.POST.get("geri", "")
    if url_has_allowed_host_and_scheme(geri, allowed_hosts={request.get_host()}):
        return redirect(geri)
    return redirect("sinavgorev:puantaj")


def _excel(bas, okul, satirlar, ist):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Puantaj"
    ws.append([f"Sınav görev puantajı {servis.yil_etiketi(bas)}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Görev puanı: hafta içi 1, hafta sonu 1,5. Skor = görev puanı + z (haftalık ders saati, "
               f"{okul or 'program seçilmedi'}; ortalama {ist['ort']:.2f}, standart sapma {ist['ss']:.2f}, {ist['n']} kişi)."
               if ist["ort"] is not None else "Görev puanı: hafta içi 1, hafta sonu 1,5. Ders saati bulunamadı; z = 0."])
    ws.append([])
    ws.append(["Personel", "Bölüm", "Roller", "Hafta içi", "Hafta sonu", "Görev puanı", "Haftalık ders", "Z", "Skor"])
    for c in ws[4]:
        c.font = Font(bold=True)
    for s in satirlar:
        p = s["personel"]
        ws.append([p.tam_ad, p.bolum.kod if p.bolum else "", p.sinav_rolleri, s["hi"], s["hs"], s["puan"], s["ders"],
                   round(s["z"], 4), round(s["skor"], 4)])
    for col, w in zip("ABCDEFGHI", (40, 10, 8, 10, 11, 12, 13, 9, 10)):
        ws.column_dimensions[col].width = w
    yanit = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    yanit["Content-Disposition"] = f'attachment; filename="sinav_gorev_puantaji_{bas.year}.xlsx"'
    wb.save(yanit)
    return yanit
