import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum

from . import servis
from .models import DersMazeretBildirimi, DersMazeretDonemi
from .servis import MazeretHatasi

DURUM_FILTRELERI = [("yok", "Bildirim yok"), ("mazeretsiz", "Mazereti yok"), ("mazeretli", "Mazeretli")]


def _baglam(request, **ek):
    request.birim = birim_bul(request, servis.BIRIM_DERS)
    return {"yol": yol(request, request.birim), "y": servis.yetki(request), "breadcrumb_ek": True, **ek}  # ek ile ezilebilir


def _geri(request, varsayilan):
    hedef = request.POST.get("geri") or request.GET.get("geri")
    if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        return redirect(hedef)
    return redirect(varsayilan)


def _donem(request):
    donemler = list(DersMazeretDonemi.objects.select_related("okul"))
    secili = request.GET.get("donem") or request.POST.get("donem")
    donem = next((d for d in donemler if str(d.pk) == secili), donemler[0] if donemler else None)
    return donem, donemler


@login_required
def ders(request):
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    donem, donemler = _donem(request)
    bolum = None
    if y.kapsam_bolum is None and request.GET.get("bolum", "").isdigit():
        bolum = Bolum.objects.filter(pk=request.GET["bolum"]).first()
    durum = request.GET.get("durum", "")
    satirlar, sayilar, bolum_ozeti = [], {}, []
    if donem:
        bildirimler = {b.personel_id: b for b in donem.bildirimler.select_related("bildiren")}
        tum = list(servis.personeller(y, bolum))
        for p in tum:
            b = bildirimler.get(p.pk)
            p.bildirim = b
            p.mazeret_durumu = "yok" if b is None else ("mazeretli" if b.hucreler else "mazeretsiz")
        sayilar = {k: sum(1 for p in tum if p.mazeret_durumu == k) for k, _ in DURUM_FILTRELERI}
        satirlar = [p for p in tum if not durum or p.mazeret_durumu == durum]
        if y.kapsam_bolum is None and bolum is None:
            ozet = {}
            for p in tum:
                o = ozet.setdefault(p.bolum, {"bolum": p.bolum, "toplam": 0, "bildirilen": 0})
                o["toplam"] += 1
                o["bildirilen"] += p.bildirim is not None
            bolum_ozeti = sorted(ozet.values(), key=lambda o: (o["bolum"] is None, getattr(o["bolum"], "ad", "")))
    return render(request, "mazeret/ders.html", _baglam(
        request, breadcrumb_ek=False, donem=donem, donemler=donemler, satirlar=satirlar, sayilar=sayilar, durum=durum,
        filtreler=DURUM_FILTRELERI, toplam=sum(sayilar.values()), bolum_ozeti=bolum_ozeti,
        bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [], secili_bolum=bolum,
        degistirebilir=bool(donem) and servis.degistirebilir_mi(y, donem),
    ))


@login_required
def bildirim(request, donem_pk, personel_pk):
    y = servis.yetki(request)
    donem = get_object_or_404(DersMazeretDonemi, pk=donem_pk)
    personel = servis.kapsamdaki_personel(y, personel_pk)
    b = DersMazeretBildirimi.objects.filter(donem=donem, personel=personel).select_related("bildiren").first()
    degistirebilir = servis.degistirebilir_mi(y, donem)
    liste_url = f"{reverse('mazeret:ders')}?donem={donem.pk}"
    geri = request.GET.get("geri", "")
    if not url_has_allowed_host_and_scheme(geri, allowed_hosts={request.get_host()}):
        geri = ""
    if request.method == "POST":
        try:
            hucreler = json.loads(request.POST.get("hucreler") or "{}")
            surum = int(request.POST.get("surum") or 0)
            servis.kaydet(request.user, y, donem, personel, hucreler, request.POST.get("aciklama"), surum)
        except (ValueError, TypeError):
            messages.error(request, "Form okunamadı; sayfayı yenileyip tekrar deneyin.")
        except MazeretHatasi as e:
            messages.error(request, str(e))
        else:
            b = DersMazeretBildirimi.objects.get(donem=donem, personel=personel)
            ozet = f"{b.yasak_sayisi} saat ✗, {b.kosullu_sayisi} saat ?" if b.hucreler else "mazereti yok"
            messages.success(request, f"{personel.ad_soyad}: bildirim kaydedildi ({ozet}).")
            if donem.okul_id:
                aktarilan, _ = servis.programa_aktar(donem, [b])
                if aktarilan:
                    messages.info(request, f"Program Hazırlama'da “{donem.okul}” programındaki müsaitliğe işlendi.")
                else:
                    messages.warning(request, f"Program Hazırlama'da “{donem.okul}” programında bu personelle eşleşen öğretmen bulunamadı; müsaitliğe işlenmedi.")
            if request.POST.get("sonraki"):
                return redirect("mazeret:bildirim", donem_pk=donem.pk, personel_pk=request.POST["sonraki"])
            return _geri(request, liste_url)
        return redirect(request.get_full_path())
    # Aynı listede sıradaki bildirimsiz personel ("Kaydet ve sıradaki")
    sonraki = None
    if degistirebilir:
        bildirimli = set(donem.bildirimler.values_list("personel_id", flat=True))
        kapsam = [p for p in servis.personeller(y, personel.bolum if y.kapsam_bolum is None else None)]
        sonraki = next((p for p in kapsam if p.pk not in bildirimli and p.pk != personel.pk), None)
    return render(request, "mazeret/bildirim.html", _baglam(
        request, donem=donem, personel=personel, b=b, degistirebilir=degistirebilir, sonraki=sonraki,
        # Saat aralığı yazılmaz: Cuma öğle arası farklı olduğu için yanıltıcı olur.
        saatler=range(1, donem.saat_sayisi + 1), gunler=list(enumerate(donem.gunler)),
        hucreler_json=json.dumps(b.hucreler if b else {}), liste_url=liste_url, geri=geri,
        gecmis=list(b.gecmis.select_related("kullanici")[:10]) if b else [],
    ))


@require_POST
@login_required
def toplu(request, donem_pk):
    y = servis.yetki(request)
    donem = get_object_or_404(DersMazeretDonemi, pk=donem_pk)
    secilen = [servis.kapsamdaki_personel(y, pk) for pk in request.POST.getlist("p") if pk.isdigit()]
    if not secilen:
        messages.error(request, "Hiç personel seçilmedi.")
    else:
        try:
            yapilan = servis.toplu_mazeretsiz(request.user, y, donem, secilen)
        except MazeretHatasi as e:
            messages.error(request, str(e))
        else:
            atlanan = len(secilen) - len(yapilan)
            messages.success(request, f"{len(yapilan)} personel için “mazereti yok” kaydedildi."
                             + (f" {atlanan} personelin zaten bildirimi vardı, değiştirilmedi." if atlanan else ""))
            if yapilan and donem.okul_id:
                servis.programa_aktar(donem, yapilan)
    return _geri(request, f"{reverse('mazeret:ders')}?donem={donem.pk}")


@require_POST
@login_required
def aktar(request, donem_pk):
    y = servis.yetki(request)
    if not y.yonetim or y.kapsam_bolum is not None:
        raise PermissionDenied
    donem = get_object_or_404(DersMazeretDonemi, pk=donem_pk)
    if donem.okul is None:
        messages.error(request, "Bu dönem bir Program Hazırlama programına bağlı değil (Yönetim Paneli → Ders mazeret dönemleri).")
    else:
        aktarilan, eslesmeyen = servis.programa_aktar(donem)
        messages.success(request, f"{len(aktarilan)} personelin mazereti “{donem.okul}” programına aktarıldı.")
        if eslesmeyen:
            adlar = ", ".join(b.personel.ad_soyad for b in eslesmeyen[:15]) + (" …" if len(eslesmeyen) > 15 else "")
            messages.warning(request, f"{len(eslesmeyen)} personel programdaki bir öğretmenle eşleşmedi: {adlar}")
    return redirect(f"{reverse('mazeret:ders')}?donem={donem.pk}")
