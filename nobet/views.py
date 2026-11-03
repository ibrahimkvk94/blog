from collections import OrderedDict
from datetime import date

from django.contrib import messages
from django.db.models import Count, F, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.yetki import YONETIM, yetki_gerekli, yol
from personel.models import Bolum, Personel, Secenek

from . import servis
from .excel import ek3
from .models import AYLAR, NobetAtamasi, NobetAyari, NobetDonemi, NobetGorevi, NobetKisitlamasi, NobetKontenjani
from .servis import NobetHatasi

BIRIM = "nobet-gruplari"


def _baglam(request, **ek):
    return {"yol": yol(request, request.birim), "yonetici": request.yetki_seviye >= YONETIM, **ek}


def _sonraki_ay():
    b = timezone.localdate()
    return (b.year, b.month + 1) if b.month < 12 else (b.year + 1, 1)


@yetki_gerekli(BIRIM)
def ana(request):
    if request.method == "POST":
        if request.yetki_seviye < YONETIM:
            messages.error(request, "Bu işlem için yetkiniz yok.")
            return redirect("nobet:ana")
        try:
            yil, ay = int(request.POST["yil"]), int(request.POST["ay"])
            assert 2020 <= yil <= 2100 and 1 <= ay <= 12
        except (KeyError, ValueError, AssertionError):
            messages.error(request, "Geçerli bir ay seçin.")
            return redirect("nobet:ana")
        d, olustu = NobetDonemi.objects.get_or_create(yil=yil, ay=ay, defaults={"olusturan": request.user})
        if olustu:
            rapor = servis.dagit(d)
            messages.success(request, f"{d} nöbet grupları oluşturuldu: {rapor.atanan} kişi dağıtıldı.")
        return redirect("nobet:donem", yil=yil, ay=ay)
    donemler = NobetDonemi.objects.annotate(kisi=Count("atamalar"))
    sy, sa = _sonraki_ay()
    ayar = NobetAyari.al()
    return render(request, "nobet/ana.html", _baglam(
        request, donemler=donemler, sonraki_yil=sy, sonraki_ay=sa, aylar=list(enumerate(AYLAR, start=1)),
        yillar=range(timezone.localdate().year - 1, timezone.localdate().year + 2),
        gorev_sayisi=NobetGorevi.objects.filter(aktif=True).count(),
        tutar=Personel.objects.filter(aktif=True, nobet_durumu=Personel.NOBET_TUTAR).exclude(rutbe=None).count(),
        rutbesiz=Personel.objects.filter(aktif=True, nobet_durumu=Personel.NOBET_TUTAR, rutbe=None).count(),
        ayar=ayar,
    ))


def _donem(yil, ay):
    return get_object_or_404(NobetDonemi, yil=yil, ay=ay)


@yetki_gerekli(BIRIM)
def donem(request, yil, ay):
    d = _donem(yil, ay)
    gorevler = list(NobetGorevi.objects.filter(aktif=True).prefetch_related("izinli_rutbeler"))
    atamalar = list(d.atamalar.select_related("personel__rutbe", "personel__sinif", "personel__unvan", "gorev"))
    gec = servis.gecmis(d)
    for a in atamalar:
        g = gec.get(a.personel_id, servis.Gecmis())
        a.yil_yatili, a.yil_puan = g.yatili, g.puan
    gruplar = OrderedDict((g, []) for g in gorevler)
    for a in sorted(atamalar, key=lambda a: (-(a.personel.rutbe.pk if a.personel.rutbe else 0), a.personel.ad_soyad)):
        gruplar.setdefault(a.gorev, []).append(a)
    for g, liste in gruplar.items():
        g.atamalar_listesi = liste
        g.rutbe_metni = ", ".join(r.metin for r in g.izinli_rutbeler.all()) or "Rütbe tanımlı değil"
    atanan = {a.personel_id for a in atamalar}
    bosta = [p for p in servis.uygun_personel(d) if p.pk not in atanan]
    muaflar = list(servis.muaf_personel(d))
    onceki = NobetDonemi.objects.filter(Q(yil__lt=d.yil) | Q(yil=d.yil, ay__lt=d.ay)).first()
    return render(request, "nobet/donem.html", _baglam(
        request, d=d, gruplar=gruplar, atamalar=sorted(atamalar, key=lambda a: a.personel.ad_soyad), bosta=bosta,
        muaflar=muaflar, uyarilar=servis.adalet_uyarilari(d), kural_disi=servis.kural_disi_atamalar(d),
        onceki_taslak=onceki if onceki and onceki.durum == NobetDonemi.TASLAK else None,
        ayar=NobetAyari.al(), breadcrumb_ek=True,
    ))


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def islem(request, yil, ay):
    d = _donem(yil, ay)
    secim = request.POST.get("islem")
    try:
        if secim == "dagit":
            r = servis.dagit(d)
            mesaj = f"Dağıtım yapıldı: {r.atanan} kişi."
            if r.eksik:
                mesaj += " Eksik kalan: " + ", ".join(f"{g.kisa_ad} ({n})" for g, n in r.eksik) + "."
            messages.success(request, mesaj)
        elif secim == "kesinlestir":
            d.durum, d.kesinlestiren, d.kesin_zamani = NobetDonemi.KESIN, request.user, timezone.now()
            d.save(update_fields=["durum", "kesinlestiren", "kesin_zamani"])
            messages.success(request, f"{d} kesinleşti; puantaja işlendi.")
        elif secim == "taslaga_al":
            d.durum = NobetDonemi.TASLAK
            d.save(update_fields=["durum"])
            messages.info(request, f"{d} yeniden taslak.")
        elif secim == "tasi":
            a = get_object_or_404(NobetAtamasi, pk=request.POST.get("atama"), donem=d)
            g = get_object_or_404(NobetGorevi, pk=request.POST.get("gorev"))
            servis.tasi(a, g)
            messages.success(request, f"{a.personel.ad_soyad} → {g.kisa_ad}")
        elif secim == "degistir":
            a1 = get_object_or_404(NobetAtamasi, pk=request.POST.get("atama1"), donem=d)
            a2 = get_object_or_404(NobetAtamasi, pk=request.POST.get("atama2"), donem=d)
            servis.yer_degistir(a1, a2)
            messages.success(request, f"{a1.personel.ad_soyad} ↔ {a2.personel.ad_soyad} yer değiştirdi.")
        elif secim == "ekle":
            p = get_object_or_404(Personel, pk=request.POST.get("personel"))
            g = get_object_or_404(NobetGorevi, pk=request.POST.get("gorev"))
            servis.ekle(d, p, g)
            messages.success(request, f"{p.ad_soyad} → {g.kisa_ad} eklendi.")
        elif secim == "cikar":
            a = get_object_or_404(NobetAtamasi, pk=request.POST.get("atama"), donem=d)
            servis.cikar(a)
            messages.info(request, f"{a.personel.ad_soyad} gruptan çıkarıldı.")
        elif secim == "kilit_ac":
            NobetAtamasi.objects.filter(pk=request.POST.get("atama"), donem=d).update(kilitli=False)
        else:
            messages.error(request, "Geçersiz işlem.")
    except NobetHatasi as e:
        messages.error(request, str(e))
    return redirect("nobet:donem", yil=yil, ay=ay)


@yetki_gerekli(BIRIM)
def excel(request, yil, ay):
    d = _donem(yil, ay)
    yanit = HttpResponse(ek3(d), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    yanit["Content-Disposition"] = f'attachment; filename="{d.yil}_{d.ay:02d}_EK-3_NOBET_GRUPLARI.xlsx"'
    return yanit


@yetki_gerekli(BIRIM)
def puantaj(request):
    ayar = NobetAyari.al()
    bugun = timezone.localdate()
    varsayilan = bugun.year if bugun.month >= ayar.yil_baslangic_ayi else bugun.year - 1
    try:
        yil_basi = int(request.GET.get("yil", varsayilan))
    except ValueError:
        yil_basi = varsayilan
    aylar, donemler, satirlar = servis.puantaj(yil_basi)
    rutbe_sec = request.GET.get("rutbe", "")
    # rütbe gruplarına ayır, her grupta en az / en çok yatılı ve puan
    gruplar = OrderedDict()
    for p, s in sorted(satirlar.items(), key=lambda x: (-(x[0].rutbe.pk if x[0].rutbe else 0), x[0].ad_soyad)):
        if rutbe_sec.isdigit() and str(p.rutbe_id) != rutbe_sec:
            continue
        s["hucreler"] = [s["aylar"].get(ya) for ya in aylar]
        gruplar.setdefault(p.rutbe, []).append((p, s))
    ozet = []
    for rutbe, liste in gruplar.items():
        yat = [s["yatili"] for _, s in liste]
        pu = [s["puan"] for _, s in liste]
        fark = max(yat) - min(yat)
        ozet.append({"rutbe": rutbe, "kisi": len(liste), "yat_min": min(yat), "yat_max": max(yat), "fark": fark,
                     "asim": fark > ayar.yatili_fark_siniri, "puan_min": min(pu), "puan_max": max(pu)})
    return render(request, "nobet/puantaj.html", _baglam(
        request, aylar=[(y, a, AYLAR[a - 1][:3], donemler.get((y, a))) for y, a in aylar], gruplar=gruplar, ozet=ozet,
        yil_basi=yil_basi, yil_etiketi=f"{yil_basi}-{yil_basi + 1}", ayar=ayar,
        yillar=range(varsayilan - 2, varsayilan + 2), rutbeler=Secenek.objects.filter(tur=Secenek.RUTBE), rutbe_sec=rutbe_sec,
        gorevler=NobetGorevi.objects.filter(aktif=True), breadcrumb_ek=True,
    ))


@yetki_gerekli(BIRIM)
def personel(request):
    if request.method == "POST":
        js = request.headers.get("X-Istek") == "fetch"
        if request.yetki_seviye < YONETIM:
            if js:
                return JsonResponse({"ok": False, "hata": "Bu işlem için yetkiniz yok."}, status=403)
            messages.error(request, "Bu işlem için yetkiniz yok.")
            return redirect("nobet:personel")
        kisiler = list(Personel.objects.filter(pk__in=[x for x in request.POST.getlist("personel") if x.isdigit()]))
        durum = request.POST.get("durum")
        if not kisiler or durum not in dict(Personel.NOBET_DURUMLARI):
            if js:
                return JsonResponse({"ok": False, "hata": "Geçersiz seçim."}, status=400)
            return redirect(f"{request.path}?{request.POST.get('sorgu', '')}")
        try:
            bitis = date.fromisoformat(request.POST["bitis"]) if request.POST.get("bitis") else None
        except ValueError:
            bitis = None
        neden_var = "neden" in request.POST
        for p in kisiler:
            p.nobet_durumu = durum
            if durum == Personel.NOBET_TUTAR:
                p.nobet_muafiyet_nedeni, p.nobet_muafiyet_bitis = "", None
            else:
                if neden_var:  # sadece durum değiştirilirken önceki neden korunur
                    p.nobet_muafiyet_nedeni = request.POST.get("neden", "").strip()[:60]
                    p.nobet_muafiyet_bitis = bitis if durum == Personel.NOBET_MUAF else None
            p.save(update_fields=["nobet_durumu", "nobet_muafiyet_nedeni", "nobet_muafiyet_bitis"])
        if js:
            sayilar = dict(Personel.objects.filter(aktif=True).values_list("nobet_durumu").annotate(n=Count("pk")))
            return JsonResponse({"ok": True, "durum": durum, "sayilar": sayilar,
                                 "kisiler": {p.pk: {"neden": p.nobet_muafiyet_nedeni,
                                                    "bitis": p.nobet_muafiyet_bitis.isoformat() if p.nobet_muafiyet_bitis else ""}
                                             for p in kisiler}})
        messages.success(request, f"{len(kisiler)} kişi: {dict(Personel.NOBET_DURUMLARI)[durum]}")
        return redirect(f"{request.path}?{request.POST.get('sorgu', '')}")
    qs = Personel.objects.filter(aktif=True).select_related("rutbe", "sinif", "unvan", "bolum")
    q = request.GET.get("q", "").strip()
    durum = request.GET.get("durum", "")
    rutbe = request.GET.get("rutbe", "")
    if q:
        qs = qs.filter(ad_soyad__icontains=q)
    if durum in dict(Personel.NOBET_DURUMLARI):
        qs = qs.filter(nobet_durumu=durum)
    if rutbe == "yok":
        qs = qs.filter(rutbe=None)
    elif rutbe.isdigit():
        qs = qs.filter(rutbe_id=rutbe)
    bolum = request.GET.get("bolum", "")
    if bolum.isdigit():
        qs = qs.filter(bolum_id=bolum)

    # sıralama: ?sirala=ad | rutbe | bolum | durum, başında "-" azalan
    siralar = {
        "ad": [F("ad_soyad").asc()],
        "rutbe": [F("rutbe__sira").desc(nulls_last=True), F("ad_soyad").asc()],  # artan = kıdemliden başla
        "bolum": [F("bolum__ad").asc(nulls_last=True), F("ad_soyad").asc()],
        "durum": [F("nobet_durumu").asc(), F("ad_soyad").asc()],
    }
    sirala = request.GET.get("sirala", "ad")
    alan, azalan = sirala.lstrip("-"), sirala.startswith("-")
    if alan not in siralar:
        alan, azalan = "ad", False
    duzen = siralar[alan]
    if azalan:
        duzen = [d.copy() for d in duzen]
        duzen[0].descending = not duzen[0].descending
    qs = qs.order_by(*duzen)
    sorgu_sirasiz = request.GET.copy()
    sorgu_sirasiz.pop("sirala", None)
    basliklar = []
    for kod, ad, sinif in (("ad", "Personel", ""), ("rutbe", "Rütbe", "d-none d-lg-table-cell"),
                           ("bolum", "Bölüm", "d-none d-md-table-cell"), ("durum", "Nöbet durumu", "")):
        yon = ("azalan" if azalan else "artan") if alan == kod else ""
        sorgu_b = sorgu_sirasiz.copy()
        sorgu_b["sirala"] = f"-{kod}" if yon == "artan" else kod
        basliklar.append({"ad": ad, "yon": yon, "url": "?" + sorgu_b.urlencode(), "sinif": sinif})

    sayilar = dict(Personel.objects.filter(aktif=True).values_list("nobet_durumu").annotate(n=Count("pk")))
    return render(request, "nobet/personel.html", _baglam(
        request, liste=qs, q=q, durum=durum, rutbe=rutbe, bolum=bolum, sorgu=request.GET.urlencode(),
        basliklar=basliklar, sirala=sirala, bolumler=Bolum.objects.filter(aktif=True),
        rutbeler=Secenek.objects.filter(tur=Secenek.RUTBE), durumlar=Personel.NOBET_DURUMLARI,
        sayilar=[(k, ad, sayilar.get(k, 0)) for k, ad in Personel.NOBET_DURUMLARI], toplam=sum(sayilar.values()),
        rutbesiz=Personel.objects.filter(aktif=True, rutbe=None).count(),
        nedenler=["YDGG", "YİGG", "Geçici süre ile muaf", "Kütüphane vardiya"], breadcrumb_ek=True,
    ))


# ---------------------------------------------------------------- yıllık plan

def _yil_basi(request, ayar):
    bugun = timezone.localdate()
    varsayilan = bugun.year if bugun.month >= ayar.yil_baslangic_ayi else bugun.year - 1
    try:
        return int(request.GET.get("yil") or request.POST.get("yil") or varsayilan), varsayilan
    except ValueError:
        return varsayilan, varsayilan


@yetki_gerekli(BIRIM)
def yillik(request):
    ayar = NobetAyari.al()
    yil_basi, varsayilan = _yil_basi(request, ayar)
    aylar = servis.yil_aylari(yil_basi)
    donemler = {(d.yil, d.ay): d for d in NobetDonemi.objects.filter(yil__in={y for y, _ in aylar})}
    donemler = {k: v for k, v in donemler.items() if k in aylar}
    atamalar = {}
    ay_kisi = {}
    for a in NobetAtamasi.objects.filter(donem__in=donemler.values()).select_related("gorev", "donem"):
        atamalar[(a.personel_id, a.donem.yil, a.donem.ay)] = a
        ay_kisi[(a.donem.yil, a.donem.ay)] = ay_kisi.get((a.donem.yil, a.donem.ay), 0) + 1
    atanan_kisiler = {k[0] for k in atamalar}
    kisiler = (Personel.objects.filter(aktif=True).select_related("rutbe", "sinif", "unvan")
               .filter(Q(pk__in=atanan_kisiler) | (~Q(rutbe=None) & ~Q(nobet_durumu=Personel.NOBET_TUTAMAZ))))
    rutbe_sec = request.GET.get("rutbe", "")
    if rutbe_sec.isdigit():
        kisiler = kisiler.filter(rutbe_id=rutbe_sec)
    kisitlamalar = servis.yil_kisitlamalari(yil_basi)
    satirlar = []
    for p in sorted(kisiler, key=lambda p: (-(p.rutbe.pk if p.rutbe else 0), p.ad_soyad)):
        hucreler, puan, yatili = [], 0, 0
        for y, a in aylar:
            at = atamalar.get((p.pk, y, a))
            if at:
                puan += at.gorev.puan
                yatili += 1 if at.gorev.yatili else 0
            d = donemler.get((y, a))
            k = kisitlamalar.get((p.pk, y, a))
            ilk, son = servis.ay_araligi(y, a)
            engel = "" if not k else ("ay" if k.tur == "yazilamaz" and k.baslangic >= ilk and k.bitis and k.bitis <= son else "uzun")
            hucreler.append({"y": y, "a": a, "at": at, "d": d, "muaf": servis.muaf_etiketi(p, y, a, kisitlamalar),
                             "kis": k, "engel": engel, "duz": d is None or d.durum == NobetDonemi.TASLAK})
        satirlar.append((p, {"hucreler": hucreler, "puan": puan, "yatili": yatili}))

    gorevler = list(NobetGorevi.objects.filter(aktif=True).prefetch_related("izinli_rutbeler"))
    sablonlar = []  # rütbe başına görev seçenekleri: önce kurala uygunlar
    for rutbe in {p.rutbe for p, _ in satirlar}:
        uygun = [g for g in gorevler if rutbe and rutbe in g.izinli_rutbeler.all()]
        diger = [g for g in gorevler if g not in uygun]
        sablonlar.append({"rutbe_id": rutbe.pk if rutbe else 0, "uygun": uygun, "diger": diger})
    aylik = {(k.gorev_id, k.ay): k.kontenjan for k in NobetKontenjani.objects.all()}
    kontenjan = {(y, a): sum(g.ay_kontenjani(a, aylik) or 0 for g in gorevler if not g.sadece_sabit) for y, a in aylar}
    return render(request, "nobet/yillik.html", _baglam(
        request, yil_basi=yil_basi, yil_etiketi=f"{yil_basi}-{yil_basi + 1}", yillar=range(varsayilan - 1, varsayilan + 2),
        aylar=[{"y": y, "a": a, "ad": AYLAR[a - 1][:3], "d": donemler.get((y, a)), "kisi": ay_kisi.get((y, a), 0),
                "kontenjan": kontenjan[(y, a)]} for y, a in aylar],
        satirlar=satirlar, sablonlar=sablonlar, ozet=servis.rutbe_ozeti(satirlar, ayar.yatili_fark_siniri),
        ayar=ayar, rutbeler=Secenek.objects.filter(tur=Secenek.RUTBE), rutbe_sec=rutbe_sec,
        kesin_var=any(d.durum == NobetDonemi.KESIN for d in donemler.values()), breadcrumb_ek=True,
    ))


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def yillik_olustur(request):
    ayar = NobetAyari.al()
    yil_basi, _ = _yil_basi(request, ayar)
    baslangic = None
    if request.POST.get("baslangic"):
        try:
            y, a = (int(x) for x in request.POST["baslangic"].split("-"))
            baslangic = (y, a)
        except ValueError:
            pass
    sonuc = servis.yil_olustur(yil_basi, request.user, baslangic)
    eksik = sum(n for _, r in sonuc for _, n in r.eksik)
    messages.success(request, f"{len(sonuc)} ay dağıtıldı (kesinleşmiş aylara dokunulmadı, elle yapılanlar korundu)."
                     + (f" Toplam {eksik} kişilik kontenjan doldurulamadı." if eksik else ""))
    return redirect(f"{reverse('nobet:yillik')}?yil={yil_basi}")


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def yillik_hucre(request):
    try:
        p = Personel.objects.get(pk=request.POST.get("personel"))
        yil, ay = int(request.POST.get("yil")), int(request.POST.get("ay"))
        secim = request.POST.get("gorev", "")
        if secim in ("engelle", "engel_kaldir"):
            if secim == "engelle":
                k = servis.ay_engelle(p, yil, ay, request.user)
            else:
                servis.ay_engel_kaldir(p, yil, ay)
            ayar = NobetAyari.al()
            d = NobetDonemi.objects.filter(yil=yil, ay=ay).first()
            sayi = d.atamalar.count() if d else 0
            yil_basi = yil if ay >= ayar.yil_baslangic_ayi else yil - 1
            puan, yatili = _yil_toplami(p, yil_basi)
            return JsonResponse({"ok": True, "kisa": "", "etiket": k.etiket if secim == "engelle" else "",
                                 "engel": "ay" if secim == "engelle" else "", "puan": puan, "yatili_toplam": yatili, "ay_kisi": sayi})
        gorev = NobetGorevi.objects.get(pk=secim) if secim else None
        d, _ = servis.hucre_ata(p, yil, ay, gorev, request.user)
    except (Personel.DoesNotExist, NobetGorevi.DoesNotExist, ValueError, TypeError):
        return JsonResponse({"ok": False, "hata": "Geçersiz seçim."}, status=400)
    except NobetHatasi as e:
        return JsonResponse({"ok": False, "hata": str(e)}, status=409)
    ayar = NobetAyari.al()
    puan, yatili = _yil_toplami(p, d.nobet_yili(ayar.yil_baslangic_ayi)[0])
    izinli = gorev is None or gorev.izinli_rutbeler.filter(pk=p.rutbe_id).exists()
    return JsonResponse({
        "ok": True, "kisa": gorev.kisa_ad if gorev else "", "ad": gorev.ad if gorev else "", "yatili": bool(gorev and gorev.yatili),
        "kural_disi": not izinli, "puan": puan, "yatili_toplam": yatili, "ay_kisi": d.atamalar.count(),
    })


def _yil_toplami(p, yil_basi):
    q = Q(pk__in=[])
    for y, a in servis.yil_aylari(yil_basi):
        q |= Q(donem__yil=y, donem__ay=a)
    yilin = NobetAtamasi.objects.filter(q, personel=p).select_related("gorev")
    return f"{float(sum(a.gorev.puan for a in yilin)):g}", sum(1 for a in yilin if a.gorev.yatili)

# ---------------------------------------------------------------- kısıtlamalar

@yetki_gerekli(BIRIM)
def kisitlamalar(request):
    if request.method == "POST":
        if request.yetki_seviye < YONETIM:
            messages.error(request, "Bu işlem için yetkiniz yok.")
            return redirect("nobet:kisitlamalar")
        if request.POST.get("sil"):
            k = get_object_or_404(NobetKisitlamasi, pk=request.POST["sil"])
            messages.info(request, f"Kısıtlama silindi: {k}")
            k.delete()
            return redirect(f"{reverse('nobet:kisitlamalar')}?{request.POST.get('sorgu', '')}")
        try:
            p = Personel.objects.get(pk=request.POST.get("personel"))
            bas = date.fromisoformat(request.POST.get("baslangic", ""))
            bit = date.fromisoformat(request.POST["bitis"]) if request.POST.get("bitis") else None
            tur = request.POST.get("tur")
            if tur not in dict(NobetKisitlamasi.TURLER):
                raise ValueError
            if bit and bit < bas:
                messages.error(request, "Bitiş tarihi başlangıçtan önce olamaz.")
                return redirect("nobet:kisitlamalar")
        except (Personel.DoesNotExist, ValueError):
            messages.error(request, "Personel, tür ve başlangıç tarihi zorunludur.")
            return redirect("nobet:kisitlamalar")
        k = NobetKisitlamasi.objects.create(personel=p, tur=tur, baslangic=bas, bitis=bit,
                                            aciklama=request.POST.get("aciklama", "").strip()[:150], olusturan=request.user)
        # bu dönemdeki taslak aylardan kişinin atamasını kaldır
        silinen = 0
        for d in NobetDonemi.objects.filter(durum=NobetDonemi.TASLAK):
            ilk, son = servis.ay_araligi(d.yil, d.ay)
            if bas <= son and (bit is None or bit >= ilk):
                silinen += NobetAtamasi.objects.filter(donem=d, personel=p).delete()[0]
        messages.success(request, f"Kısıtlama eklendi: {k}" + (f" · {silinen} taslak aydaki ataması kaldırıldı." if silinen else ""))
        return redirect("nobet:kisitlamalar")
    qs = NobetKisitlamasi.objects.select_related("personel__rutbe", "personel__sinif", "olusturan")
    q = request.GET.get("q", "").strip()
    tur = request.GET.get("tur", "")
    durum = request.GET.get("durum", "guncel")
    bugun = timezone.localdate()
    if q:
        qs = qs.filter(personel__ad_soyad__icontains=q)
    if tur in dict(NobetKisitlamasi.TURLER):
        qs = qs.filter(tur=tur)
    if durum == "guncel":
        qs = qs.filter(Q(bitis=None) | Q(bitis__gte=bugun.replace(day=1)))
    elif durum == "gecmis":
        qs = qs.filter(bitis__lt=bugun.replace(day=1))
    return render(request, "nobet/kisitlamalar.html", _baglam(
        request, liste=qs[:500], q=q, tur=tur, durum=durum, turler=NobetKisitlamasi.TURLER, sorgu=request.GET.urlencode(),
        personeller=Personel.objects.filter(aktif=True).select_related("rutbe", "sinif", "unvan").order_by("ad_soyad"),
        bugun=bugun, breadcrumb_ek=True,
    ))