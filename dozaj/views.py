"""Dozajmatik sayfaları: tablo, branş ayrıntısı, programlar (kısım sayıları, Excel'den yükleme), program dersleri,
branşlar (ders kodu → branş) ve öğretim elemanları (kişi → branş, kadro).

Görüntüleme Dozajmatik biriminde Görüntüleme, değişiklik Düzenleme yetkisi ister (üst birimden de gelir)."""

from collections import defaultdict

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.yetki import yetki_gerekli, yol

from . import excel, kurallar, servis
from .models import Brans, BransAyari, Ders, KisiAyari, KodBransi, Program, Yil
from .servis import BIRIM

SEKMELER = [("tablo", "Tablo", "table"), ("programlar", "Programlar", "journal-text"),
            ("branslar", "Branşlar", "diagram-3"), ("personel", "Öğretim elemanları", "people")]


def _baglam(request, yil, sekme, **ctx):
    ctx.update({"yil": yil, "yillar": Yil.objects.all(), "sekme": sekme, "sekmeler": SEKMELER,
                "duzenleyebilir": servis.duzenleyebilir(request), "yol": yol(request, request.birim)})
    return ctx


def _sayi(metin, en_cok=10000, bos=0):
    metin = (metin or "").strip()
    if metin == "":
        return bos
    if not metin.isdigit() or int(metin) > en_cok:
        raise ValueError(metin)
    return int(metin)


def _geri(request, ad, *args, kanca=""):
    return redirect(reverse(f"dozaj:{ad}", args=args) + kanca)


def _yil_yok(request):
    if request.method == "POST" and servis.duzenleyebilir(request):
        ad = (request.POST.get("ad") or "").strip()[:20]
        if ad:
            y = Yil.objects.create(ad=ad, varsayilan=True)
            request.session["dozaj_yil"] = y.pk
            messages.success(request, f"{ad} plan yılı açıldı. Şimdi programları ekleyin.")
            return redirect("dozaj:programlar")
    return render(request, "dozaj/yil_yok.html", {"duzenleyebilir": servis.duzenleyebilir(request),
                                                  "yol": yol(request, request.birim)})


# ---------------------------------------------------------------- tablo

@yetki_gerekli(BIRIM)
def tablo(request):
    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        try:
            for alan in ("uyari_esigi", "ihtiyac_saat1", "ihtiyac_saat2", "baskan_saati"):
                setattr(yil, alan, _sayi(request.POST.get(alan), 60, getattr(yil, alan)))
        except ValueError:
            messages.error(request, "Hesap ayarlarına yalnız tam sayı yazılabilir.")
        else:
            yil.save()
            messages.success(request, "Hesap ayarları kaydedildi.")
        return _geri(request, "tablo")
    h = servis.Hesap(yil)
    satirlar = h.satirlar()
    k1, k2, haz = h.kisim_toplami()
    return render(request, "dozaj/tablo.html", _baglam(
        request, yil, "tablo", satirlar=satirlar, t=h.toplamlar(satirlar), hesap_disi=h.hesap_disi(),
        kodsuz=sorted(h.kodsuz.items()), branssiz=h.branssiz, kisim1=k1, kisim2=k2, hazirlik=haz,
        program_sayisi=len(h.programlar)))


@yetki_gerekli(BIRIM)
def brans(request, pk):
    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    b = get_object_or_404(Brans, pk=pk)
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        a, _ = BransAyari.objects.get_or_create(yil=yil, brans=b)
        try:
            a.kh_sayi = _sayi(request.POST.get("kh_sayi"), 500)
            a.dis_sayi = _sayi(request.POST.get("dis_sayi"), 500)
            a.dis_saat = _sayi(request.POST.get("dis_saat"), 5000)
        except ValueError:
            messages.error(request, "Sayı kutularına yalnız tam sayı yazılabilir; kaydedilmedi.")
            return _geri(request, "brans", b.pk)
        a.atgm_dahil = request.POST.get("atgm_dahil") == "1"
        if request.POST.get("destek") in dict(BransAyari.DESTEKLER):
            a.destek = request.POST["destek"]
        a.save()
        messages.success(request, f"{b.ad} ayarları kaydedildi.")
        return _geri(request, "brans", b.pk)
    h = servis.Hesap(yil)
    satirlar = h.satirlar()
    s = next((x for x in satirlar if x.brans.pk == b.pk), None) or h.satir[b.pk]
    dersler = sorted(s.dersler, key=lambda x: (x["ders"].program.sira, x["ders"].yariyil, x["ders"].kod))
    kisiler = sorted(s.kisiler, key=lambda k: (servis.KADRO_SUTUNLARI.index(k.kadro)
                                               if k.kadro in servis.KADRO_SUTUNLARI else 9, k.personel.ad_soyad))
    return render(request, "dozaj/brans.html", _baglam(
        request, yil, "tablo", b=b, s=s, dersler=dersler, kisiler=kisiler, destekler=BransAyari.DESTEKLER,
        hesapta=b.hesapta))


# ---------------------------------------------------------------- programlar

@yetki_gerekli(BIRIM)
def programlar(request):
    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    progs = list(Program.objects.filter(yil=yil).prefetch_related("dersler"))
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        islem = request.POST.get("islem")
        if islem == "kisimlar":
            try:
                for p in progs:
                    p.kisim1 = _sayi(request.POST.get(f"k1-{p.pk}"), 200)
                    p.kisim2 = _sayi(request.POST.get(f"k2-{p.pk}"), 200)
            except ValueError:
                messages.error(request, "Kısım sayılarına yalnız tam sayı yazılabilir; kaydedilmedi.")
            else:
                Program.objects.bulk_update(progs, ["kisim1", "kisim2"])
                messages.success(request, "Kısım sayıları kaydedildi.")
        elif islem == "program_ekle":
            kod = kurallar.buyuk(request.POST.get("kod"))[:10]
            ad = (request.POST.get("ad") or "").strip()[:100]
            if kod and ad and not Program.objects.filter(yil=yil, kod=kod).exists():
                Program.objects.create(yil=yil, kod=kod, ad=ad, sira=(len(progs) + 1) * 10,
                                       hazirlik=request.POST.get("hazirlik") == "1")
                messages.success(request, f"{ad} programı eklendi.")
            else:
                messages.error(request, "Program eklenemedi: kod ve ad gerekli, kod bu yılda tek olmalı.")
        elif islem == "yeni_yil":
            ad = (request.POST.get("ad") or "").strip()[:20]
            if not ad or Yil.objects.filter(ad=ad).exists():
                messages.error(request, "Yeni yıl açılamadı: ad boş ya da zaten var.")
            else:
                y = servis.yil_kopyala(yil, ad)
                request.session["dozaj_yil"] = y.pk
                messages.success(request, f"{ad} plan yılı {yil.ad} kopyalanarak açıldı.")
        return _geri(request, "programlar")
    satirlar = []
    for p in progs:
        ds = defaultdict(int)
        for d in p.dersler.all():
            ds[d.yariyil] += d.ds
        satirlar.append({"p": p, "ders": len(p.dersler.all()), "ds": [ds[i] for i in range(1, 5)]})
    return render(request, "dozaj/programlar.html", _baglam(
        request, yil, "programlar", satirlar=satirlar, k1=sum(p.kisim1 for p in progs if not p.hazirlik),
        k2=sum(p.kisim2 for p in progs if not p.hazirlik)))


def _ders_alanlari(post, onek):
    def s(ad, en_cok=60):
        return _sayi(post.get(f"{onek}{ad}"), en_cok)

    alanlar = {"kod": kurallar.buyuk(post.get(f"{onek}kod")).replace(" ", "")[:20],
               "ad": (post.get(f"{onek}ad") or "").strip()[:200],
               "ds": s("ds"), "t": s("t"), "u": s("u"), "l": s("l"), "kr": s("kr"), "akts": s("akts"),
               "ikinci_eleman": post.get(f"{onek}ikinci") == "1"}
    g, b = (post.get(f"{onek}guz") or "").strip(), (post.get(f"{onek}bahar") or "").strip()
    alanlar["guz_kisim"] = _sayi(g, 200) if g else None
    alanlar["bahar_kisim"] = _sayi(b, 200) if b else None
    if alanlar["guz_kisim"] is not None and alanlar["bahar_kisim"] is None:
        alanlar["bahar_kisim"] = 0
    if alanlar["bahar_kisim"] is not None and alanlar["guz_kisim"] is None:
        alanlar["guz_kisim"] = 0
    return alanlar


@yetki_gerekli(BIRIM)
def program(request, pk):
    p = get_object_or_404(Program, pk=pk)
    yil = p.yil
    request.session["dozaj_yil"] = yil.pk
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        islem = request.POST.get("islem")
        try:
            with transaction.atomic():
                if islem == "kaydet":
                    sil = set(request.POST.getlist("sil"))
                    for d in p.dersler.all():
                        if str(d.pk) in sil:
                            d.delete()
                            continue
                        alanlar = _ders_alanlari(request.POST, f"d{d.pk}-")
                        if not alanlar["kod"]:
                            continue
                        for k, v in alanlar.items():
                            setattr(d, k, v)
                        d.save()
                    p.ad = (request.POST.get("program_ad") or p.ad).strip()[:100]
                    p.save(update_fields=["ad"])
                    messages.success(request, "Program kaydedildi.")
                elif islem == "ekle":
                    alanlar = _ders_alanlari(request.POST, "yeni-")
                    yy = _sayi(request.POST.get("yeni-yariyil"), 4)
                    if not alanlar["kod"] or yy not in (1, 2, 3, 4):
                        messages.error(request, "Ders eklenemedi: kod ve yarıyıl gerekli.")
                    else:
                        Ders.objects.create(program=p, yariyil=yy, sira=999, **alanlar)
                        servis.kod_branslarini_tamamla(yil)
                        messages.success(request, f"{alanlar['kod']} eklendi.")
        except ValueError:
            messages.error(request, "Sayı kutularına yalnız tam sayı yazılabilir; kaydedilmedi.")
        return _geri(request, "program", p.pk)
    kod_brans = {k.kod: k.brans for k in KodBransi.objects.filter(yil=yil).select_related("brans")}
    yariyillar = []
    for yy in range(1, 5):
        dersler = [d for d in p.dersler.all() if d.yariyil == yy]
        for d in dersler:
            d.brans = kod_brans.get(d.kod)
            d.guz_n, d.bahar_n = d.kisimlar()
        yariyillar.append({"no": yy, "dersler": dersler, "ds": sum(d.ds for d in dersler),
                           "t": sum(d.t for d in dersler), "u": sum(d.u for d in dersler),
                           "kr": sum(d.kr for d in dersler), "akts": sum(d.akts for d in dersler),
                           "yuk": sum(d.yuk for d in dersler)})
    return render(request, "dozaj/program.html", _baglam(request, yil, "programlar", p=p, yariyillar=yariyillar))


@yetki_gerekli(BIRIM)
def excel_yukle(request):
    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    servis.duzenleme_gerekli(request)
    progs = list(Program.objects.filter(yil=yil))
    if request.method == "POST" and request.POST.get("islem") == "uygula":
        sayfalar = request.session.get("dozaj_excel") or []
        by_pk = {p.pk: p for p in progs}
        n_prog = n_ders = 0
        with transaction.atomic():
            for i, sf in enumerate(sayfalar):
                hedef = request.POST.get(f"hedef-{i}")
                p = by_pk.get(int(hedef)) if hedef and hedef.isdigit() else None
                if p is None:
                    continue
                eski = {(d.yariyil, d.kod): d for d in p.dersler.all()}
                p.dersler.all().delete()
                yeni = []
                for sira, d in enumerate(sf["dersler"]):
                    e = eski.get((d["yariyil"], d["kod"]))
                    yeni.append(Ders(
                        program=p, sira=sira, **d,
                        ikinci_eleman=e.ikinci_eleman if e else d["u"] > 0,
                        guz_kisim=e.guz_kisim if e else None, bahar_kisim=e.bahar_kisim if e else None))
                Ders.objects.bulk_create(yeni)
                n_prog += 1
                n_ders += len(yeni)
            n_kod = servis.kod_branslarini_tamamla(yil)
        request.session.pop("dozaj_excel", None)
        messages.success(request, f"{n_prog} programın dersleri yüklendi ({n_ders} ders). "
                                  f"{n_kod} yeni ders koduna branş önerildi; Branşlar sekmesinden kontrol edin.")
        return redirect("dozaj:programlar")
    if request.method == "POST" and request.FILES.get("dosya"):
        f = request.FILES["dosya"]
        if f.size > 10 * 1024 * 1024:
            messages.error(request, "Dosya 10 MB'tan büyük.")
            return redirect("dozaj:programlar")
        try:
            sayfalar = excel.oku(f)
        except excel.ExcelHatasi as e:
            messages.error(request, str(e))
            return redirect("dozaj:programlar")
        request.session["dozaj_excel"] = sayfalar
        onizleme = []
        for i, sf in enumerate(sayfalar):
            p = excel.eslestir(sf, progs)
            ds = defaultdict(int)
            for d in sf["dersler"]:
                ds[d["yariyil"]] += d["ds"]
            onizleme.append({"i": i, "sf": sf, "eslesen": p, "ds": [ds[k] for k in range(1, 5)],
                             "mevcut": len(p.dersler.all()) if p else 0})
        return render(request, "dozaj/excel.html", _baglam(request, yil, "programlar", onizleme=onizleme,
                                                           progs=progs))
    return redirect("dozaj:programlar")


# ---------------------------------------------------------------- branşlar

@yetki_gerekli(BIRIM)
def branslar(request):
    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    tum = list(Brans.objects.all())
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        islem = request.POST.get("islem")
        if islem == "kodlar":
            by_pk = {str(b.pk): b for b in tum}
            mevcut = {k.kod: k for k in KodBransi.objects.filter(yil=yil)}
            degisen = 0
            for anahtar, deger in request.POST.items():
                if not anahtar.startswith("kod-"):
                    continue
                kod = anahtar[4:]
                k = mevcut.get(kod)
                b = by_pk.get(deger)
                if b is None:
                    if k:
                        k.delete()
                        degisen += 1
                elif k is None:
                    KodBransi.objects.create(yil=yil, kod=kod, brans=b)
                    degisen += 1
                elif k.brans_id != b.pk:
                    k.brans = b
                    k.save(update_fields=["brans"])
                    degisen += 1
            messages.success(request, f"Ders kodu branşları kaydedildi ({degisen} değişiklik).")
        elif islem == "brans_ekle":
            ad = kurallar.buyuk(request.POST.get("ad"))[:40]
            grup = kurallar.buyuk(request.POST.get("grup"))[:60] or ad
            if ad and not Brans.objects.filter(ad=ad).exists():
                Brans.objects.create(ad=ad, grup=grup, sira=(max((b.sira for b in tum), default=0) + 10),
                                     hesapta=request.POST.get("hesapta") == "1")
                messages.success(request, f"{ad} branşı eklendi.")
            else:
                messages.error(request, "Branş eklenemedi: ad boş ya da zaten var.")
        return _geri(request, "branslar")
    kodlar = defaultdict(lambda: {"programlar": set(), "ad": "", "ds": 0})
    for d in Ders.objects.filter(program__yil=yil).select_related("program"):
        k = kodlar[d.kod]
        k["programlar"].add(d.program.kod)
        k["ad"] = k["ad"] or d.ad
        k["ds"] = d.ds
    secili = {k.kod: k.brans_id for k in KodBransi.objects.filter(yil=yil)}
    gruplar = defaultdict(list)
    for kod in sorted(kodlar):
        k = kodlar[kod]
        oneri = kurallar.kod_bransi(kod)
        gruplar[kod[:3]].append({"kod": kod, "ad": k["ad"], "ds": k["ds"], "programlar": sorted(k["programlar"]),
                                 "secili": secili.get(kod), "oneri": oneri})
    eksik = sum(1 for kod in kodlar if kod not in secili)
    return render(request, "dozaj/branslar.html", _baglam(
        request, yil, "branslar", gruplar=sorted(gruplar.items()), tum=tum, eksik=eksik))


# ---------------------------------------------------------------- öğretim elemanları

@yetki_gerekli(BIRIM)
def personel(request):
    from personel.models import Bolum

    yil = servis.yil_sec(request)
    if yil is None:
        return _yil_yok(request)
    tum = list(Brans.objects.all())
    kisiler = servis.kisiler(yil, {b.ad: b for b in tum})
    if request.method == "POST":
        servis.duzenleme_gerekli(request)
        by_pk = {str(b.pk): b for b in tum}
        kadrolar = dict(KisiAyari.KADROLAR)
        degisen = 0
        for k in kisiler:
            pid = k.personel.pk
            if f"b-{pid}" not in request.POST:
                continue
            bsec = request.POST.get(f"b-{pid}")  # "" = öneri, "yok" = derse girmiyor, pk = branş
            ksec = request.POST.get(f"k-{pid}", "")  # "" = otomatik
            brans = by_pk.get(bsec)
            brans_yok = bsec == "yok"
            kadro = ksec if ksec in kadrolar else ""
            a = k.ayar
            if not brans and not brans_yok and not kadro:
                if a:
                    a.delete()
                    degisen += 1
                continue
            if a is None:
                a = KisiAyari(yil=yil, personel=k.personel)
            elif (a.brans_id, a.brans_yok, a.kadro) == (getattr(brans, "pk", None), brans_yok, kadro):
                continue
            a.brans, a.brans_yok, a.kadro, a.guncelleyen = brans, brans_yok, kadro, request.user
            a.save()
            degisen += 1
        messages.success(request, f"Öğretim elemanları kaydedildi ({degisen} değişiklik).")
        from urllib.parse import urlencode

        q = {k: request.POST.get(k) for k in ("bolum", "durum") if request.POST.get(k)}
        return redirect(reverse("dozaj:personel") + (f"?{urlencode(q)}" if q else ""))
    bolumler = list(Bolum.objects.filter(aktif=True).order_by("ad"))
    secili = request.GET.get("bolum", "")
    durum = request.GET.get("durum", "")
    goster = []
    for k in kisiler:
        p = k.personel
        if secili == "yok":
            if p.bolum_id:
                continue
        elif secili and str(p.bolum_id) != secili:
            continue
        if durum == "branssiz":
            if k.brans or not p.derse_girebilir or (k.ayar and k.ayar.brans_yok):
                continue
        elif durum != "hepsi" and not (p.derse_girebilir or k.brans or k.ayar):
            continue
        goster.append(k)
    goster.sort(key=lambda k: (str(k.personel.bolum or "~"), k.brans.sira if k.brans else 9999,
                               k.personel.ad_soyad))
    ozet = defaultdict(int)
    for k in kisiler:
        if k.brans:
            ozet["branslu"] += 1
        elif k.personel.derse_girebilir and not (k.ayar and k.ayar.brans_yok):
            ozet["branssiz"] += 1
    return render(request, "dozaj/personel.html", _baglam(
        request, yil, "personel", kisiler=goster, bolumler=bolumler, secili=secili, durum=durum, tum=tum,
        kadrolar=KisiAyari.KADROLAR, ozet=ozet, kadro_kisa=servis.KADRO_KISA))
