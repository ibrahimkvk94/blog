"""Ders ve sınav mazereti sayfaları. İki tür aynı görünümleri kullanır; tür url'den gelir (servis.TURLER)."""

import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum

from . import servis
from .servis import TURLER, MazeretHatasi

DURUM_FILTRELERI = [("yok", "Bildirim yok"), ("mazeretsiz", "Mazereti yok"), ("mazeretli", "Mazeretli")]


def _baglam(request, tur, **ek):
    request.birim = birim_bul(request, tur.birim)
    return {"yol": yol(request, request.birim), "y": servis.yetki(request, tur), "tur": tur, "breadcrumb_ek": True,
            "u": {ad: tur.url(ad) for ad in ("liste", "bildirim", "toplu", "aktar", "tablo", "teslim")}, **ek}  # ek ile ezilebilir


def _geri(request, varsayilan):
    hedef = request.POST.get("geri") or request.GET.get("geri")
    if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        return redirect(hedef)
    return redirect(varsayilan)


def _donem(request, tur):
    donemler = list(tur.donem_modeli.objects.all())
    secili = request.GET.get("donem") or request.POST.get("donem")
    donem = next((d for d in donemler if str(d.pk) == secili), donemler[0] if donemler else None)
    return donem, donemler


def _liste_url(tur, donem):
    return f"{reverse(tur.url('liste'))}?donem={donem.pk}&liste=1"


def _tablo_url(tur, donem, bolum=None):
    url = reverse(tur.url("tablo"), args=[donem.pk])
    return f"{url}?bolum={bolum.pk}" if bolum is not None else url


@login_required
def liste(request, tur):
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    if not y.goruntule:
        raise PermissionDenied
    donem, donemler = _donem(request, tur)
    # Açılış ekranı toplu tablodur (09.11.2026); kişi kişi liste ?liste=1 ile (filtreli bağlantılar da listeyi açar).
    if donem and not request.GET.get("liste") and not request.GET.get("durum"):
        bolum = None
        if y.kapsam_bolum is None:
            pk = request.GET.get("bolum", "")
            bolum = BOLUMSUZ if pk == "yok" else (Bolum.objects.filter(pk=pk).first() if pk.isdigit() else None)
        return redirect(_tablo_url(tur, donem, bolum))
    bolum = None
    if y.kapsam_bolum is None and request.GET.get("bolum", "").isdigit():
        bolum = Bolum.objects.filter(pk=request.GET["bolum"]).first()
    durum = request.GET.get("durum", "")
    satirlar, sayilar, bolum_ozeti, gecersiz, teslimler, bolumsuz_ozet = [], {}, [], 0, [], None
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
        if tur.kod == "sinav" and y.yonetim:
            gecersiz = servis.gecersiz_isaretler(donem)
        teslimler = servis.bolum_durumlari(tur, donem, y)
        bolumsuz = [p for p in tum if p.bolum_id is None]
        bolumsuz_ozet = {"toplam": len(bolumsuz), "bildirilen": sum(1 for p in bolumsuz if p.bildirim)}
    return render(request, "mazeret/liste.html", _baglam(
        request, tur, breadcrumb_ek=False, donem=donem, donemler=donemler, satirlar=satirlar, sayilar=sayilar,
        durum=durum, filtreler=DURUM_FILTRELERI, toplam=sum(sayilar.values()), bolum_ozeti=bolum_ozeti,
        bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [], secili_bolum=bolum,
        degistirebilir=bool(donem) and servis.degistirebilir_mi(y, donem),
        hedef=servis.hedef_adi(tur, donem) if donem else None, gecersiz=gecersiz, teslimler=teslimler,
        bolumsuz_ozet=bolumsuz_ozet if y.kapsam_bolum is None and bolum is None else None,
        teslim_eden=sum(1 for s in teslimler if s["teslim"]),
        kalan_gun=(donem.son_bildirim.date() - timezone.localdate()).days if donem and donem.son_bildirim else None,
        admin_liste=f"admin:mazeret_{tur.model_adi}_changelist", admin_ekle=f"admin:mazeret_{tur.model_adi}_add",
    ))


@login_required
def bildirim(request, donem_pk, personel_pk, tur):
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    donem = get_object_or_404(tur.donem_modeli, pk=donem_pk)
    personel = servis.kapsamdaki_personel(y, personel_pk)
    b = donem.bildirimler.filter(personel=personel).select_related("bildiren").first()
    degistirebilir = servis.degistirebilir_mi(y, donem)
    liste_url = _liste_url(tur, donem)
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
            b = donem.bildirimler.get(personel=personel)
            ozet = (f"{b.yasak_sayisi} {tur.birim_adi} ✗, {b.kosullu_sayisi} {tur.birim_adi} ?" if b.hucreler
                    else "mazereti yok")
            messages.success(request, f"{personel.ad_soyad}: bildirim kaydedildi ({ozet}).")
            hedef = servis.hedef_adi(tur, donem)
            if hedef:
                aktarilan, _ = servis.aktar(tur, donem, [b])
                if aktarilan:
                    messages.info(request, f"{hedef} güncellendi.")
                else:
                    messages.warning(request, f"{hedef} güncellenmedi: bu personelle eşleşen öğretmen bulunamadı.")
            if request.POST.get("sonraki"):
                return redirect(tur.url("bildirim"), donem_pk=donem.pk, personel_pk=request.POST["sonraki"])
            return _geri(request, liste_url)
        return redirect(request.get_full_path())
    # Aynı listede sıradaki bildirimsiz personel ("Kaydet ve sıradaki")
    sonraki = None
    if degistirebilir:
        bildirimli = set(donem.bildirimler.values_list("personel_id", flat=True))
        kapsam = [p for p in servis.personeller(y, personel.bolum if y.kapsam_bolum is None else None)]
        sonraki = next((p for p in kapsam if p.pk not in bildirimli and p.pk != personel.pk), None)
    sutunlar, satirlar = donem.izgara()
    izinler = servis.izin_isaretleri(donem, [personel.pk]).get(personel.pk, {}) if tur.kod == "sinav" else {}
    return render(request, "mazeret/bildirim.html", _baglam(
        request, tur, donem=donem, personel=personel, b=b, degistirebilir=degistirebilir, sonraki=sonraki,
        sutunlar=sutunlar, satirlar=satirlar,
        hucreler_json=json.dumps(b.hucreler if b else {}), liste_url=liste_url, geri=geri, izinler=izinler,
        gecmis=list(b.gecmis.select_related("kullanici")[:10]) if b else [],
    ))


@require_POST
@login_required
def toplu(request, donem_pk, tur):
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    donem = get_object_or_404(tur.donem_modeli, pk=donem_pk)
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
            if yapilan and servis.hedef_adi(tur, donem):
                servis.aktar(tur, donem, yapilan)
    return _geri(request, _liste_url(tur, donem))


@require_POST
@login_required
def aktar(request, donem_pk, tur):
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    if not y.yonetim or y.kapsam_bolum is not None:
        raise PermissionDenied
    donem = get_object_or_404(tur.donem_modeli, pk=donem_pk)
    hedef = servis.hedef_adi(tur, donem)
    if hedef is None:
        messages.error(request, "Bu dönem bağlı bir programa / sınav dönemine bağlı değil (Yönetim Paneli → mazeret dönemleri).")
    else:
        aktarilan, eslesmeyen = servis.aktar(tur, donem)
        messages.success(request, f"{len(aktarilan)} personelin mazereti aktarıldı: {hedef}.")
        if eslesmeyen:
            adlar = ", ".join(b.personel.ad_soyad for b in eslesmeyen[:15]) + (" …" if len(eslesmeyen) > 15 else "")
            messages.warning(request, f"{len(eslesmeyen)} personel programdaki bir öğretmenle eşleşmedi: {adlar}")
    return redirect(_liste_url(tur, donem))


# ---------------------------------------------------------------- toplu tablo ve bölüm teslimi

class BolumsuzTablo:
    """Tüm okulu görenler için: bölümü olmayan (idari birimlerdeki) personelin tablosu. Teslimi yoktur."""

    pk = "yok"
    ad = "Bölümü olmayanlar (idari birimler)"


BOLUMSUZ = BolumsuzTablo()


def _tablo_bolumu(request, y):
    """Tablonun bölümü: bölüm hesabında kendi bölümü; tüm okulu görende ?bolum= ile seçilen (yoksa None);
    ?bolum=yok → bölümü olmayan personel."""
    if y.kapsam_bolum is not None:
        return y.kapsam_bolum
    pk = request.GET.get("bolum") or request.POST.get("bolum") or ""
    if pk == "yok":
        return BOLUMSUZ
    return Bolum.objects.filter(pk=pk).first() if pk.isdigit() else None


@login_required
def tablo(request, donem_pk, tur):
    """Bölümün bütün personeli tek tabloda: satır = personel, sütun = gün × oturum (ders: gün × saat). Hücreye tıklayınca
    seçili işaret konur; kaydedince tablodaki herkes bildirilmiş sayılır (boş satır = mazereti yok)."""
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    if not y.goruntule:
        raise PermissionDenied
    donem = get_object_or_404(tur.donem_modeli, pk=donem_pk)
    bolum = _tablo_bolumu(request, y)
    degistirebilir = servis.degistirebilir_mi(y, donem)
    if request.method == "POST":
        if bolum is None:
            raise PermissionDenied
        try:
            veriler = json.loads(request.POST.get("veriler") or "{}")
            surumler = json.loads(request.POST.get("surumler") or "{}")
            aciklamalar = json.loads(request.POST.get("aciklamalar") or "{}")
            kaydedilen, degismeyen = servis.toplu_kaydet(request.user, y, donem, veriler, surumler, aciklamalar)
        except (ValueError, TypeError):
            messages.error(request, "Tablo okunamadı; sayfayı yenileyip tekrar deneyin.")
        except MazeretHatasi as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f"{len(kaydedilen)} personelin bildirimi kaydedildi"
                             + (f", {degismeyen} personelinki değişmedi" if degismeyen else "") + ".")
            if kaydedilen and servis.hedef_adi(tur, donem):
                _, eslesmeyen = servis.aktar(tur, donem, kaydedilen)
                if eslesmeyen:
                    adlar = ", ".join(b.personel.ad_soyad for b in eslesmeyen[:10]) + (" …" if len(eslesmeyen) > 10 else "")
                    messages.warning(request, f"{len(eslesmeyen)} personel {'Sınav Planlama' if tur.kod == 'sinav' else 'Program Hazırlama'}'daki "
                                              f"bir öğretmenle eşleşmedi, mazereti oraya yazılmadı: {adlar}")
        return redirect(_tablo_url(tur, donem, bolum))
    sutunlar, satirlar_izgara = donem.izgara()
    donemler = list(tur.donem_modeli.objects.all())
    gruplar = [(etiket, [k for k, _ in hucreler]) for etiket, hucreler in satirlar_izgara]
    kisiler, veriler, surumler, izinler, durum = [], {}, {}, {}, None
    if bolum is not None:
        kisiler = list(servis.personeller(y).filter(bolum__isnull=True) if bolum is BOLUMSUZ
                       else servis.personeller(y, bolum))
        bildirimler = {b.personel_id: b for b in donem.bildirimler.filter(personel__in=kisiler)}
        izinler = servis.izin_isaretleri(donem, [p.pk for p in kisiler]) if tur.kod == "sinav" else {}
        for p in kisiler:
            b = bildirimler.get(p.pk)
            p.bildirim = b
            p.izinler = izinler.get(p.pk, {})
            veriler[str(p.pk)] = b.hucreler if b else {}
            surumler[str(p.pk)] = b.surum if b else 0
        if bolum is not BOLUMSUZ:
            durum = next(iter(servis.bolum_durumlari(tur, donem, y, {bolum.pk})), None)
    # bölüm seçilmemişse (tüm okulu görenler) bölümlerin teslim panosu
    teslimler, bolumsuz_ozet = [], None
    if bolum is None and y.kapsam_bolum is None:
        teslimler = servis.bolum_durumlari(tur, donem, y)
        bolumsuz = list(servis.personeller(y).filter(bolum__isnull=True).values_list("pk", flat=True))
        bolumsuz_ozet = {"toplam": len(bolumsuz),
                         "bildirilen": donem.bildirimler.filter(personel_id__in=bolumsuz).count()}
    return render(request, "mazeret/tablo.html", _baglam(
        request, tur, donem=donem, bolum=bolum, kisiler=kisiler, sutunlar=sutunlar, gruplar=gruplar,
        veriler=veriler, surumler_json=json.dumps(surumler),
        izinler_d={str(k): v for k, v in izinler.items()}, degistirebilir=degistirebilir,
        durum=durum, bolumler=Bolum.objects.filter(aktif=True) if y.kapsam_bolum is None else [],
        liste_url=_liste_url(tur, donem), donemler=donemler,
        teslimler=teslimler, bolumsuz_ozet=bolumsuz_ozet, teslim_eden=sum(1 for s in teslimler if s["teslim"]),
        kalan_gun=(donem.son_bildirim.date() - timezone.localdate()).days if donem.son_bildirim else None,
        hedef=servis.hedef_adi(tur, donem), admin_liste=f"admin:mazeret_{tur.model_adi}_changelist",
    ))


@require_POST
@login_required
def teslim(request, donem_pk, tur):
    tur = TURLER[tur]
    y = servis.yetki(request, tur)
    donem = get_object_or_404(tur.donem_modeli, pk=donem_pk)
    bolum = _tablo_bolumu(request, y)
    if bolum is None or bolum is BOLUMSUZ:
        raise PermissionDenied
    try:
        servis.teslim_et(request.user, y, tur, donem, bolum)
    except MazeretHatasi as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{bolum.ad}: {tur.tekil.lower()} bildirimi teslim edildi.")
    return _geri(request, _tablo_url(tur, donem, bolum))
