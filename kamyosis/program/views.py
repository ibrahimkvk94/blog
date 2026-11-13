import colorsys
import zlib

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from bildirim import servis as bildirim
from core.arama import ara
from core.yetki import YONETIM, yetki_gerekli, yol
from personel.models import Personel

from . import eslestirme
from .asc import AscHatasi, ice_aktar
from .forms import YayinForm, YuklemeForm
from .models import GUNLER, Derslik, Kisim, ProgramHucresi, ProgramOgretmeni, ProgramSurumu

BIRIM = "ders-planlari"


def _baglam(request, **ek):
    return {"yol": yol(request, request.birim), "yonetici": request.yetki_seviye >= YONETIM, **ek}


def _renk(anahtar):
    """Ders kodu önekine göre sabit, okunaklı bir pastel renk."""
    ton = (zlib.crc32((anahtar or "").encode()) % 360) / 360
    r, g, b = colorsys.hls_to_rgb(ton, 0.92, 0.55)
    kr, kg, kb = colorsys.hls_to_rgb(ton, 0.42, 0.5)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}", f"#{int(kr*255):02x}{int(kg*255):02x}{int(kb*255):02x}"


@yetki_gerekli(BIRIM)
def ana(request):
    gecerli = ProgramSurumu.objects.gecerli()
    surumler = ProgramSurumu.objects.annotate(ders_sayisi=Count("dersler", distinct=True))[:8]
    bekleyen = ProgramOgretmeni.objects.filter(durum=ProgramOgretmeni.BEKLIYOR).count()
    from takip.models import DevirTalebi
    devir_bekleyen = DevirTalebi.objects.filter(durum__in=DevirTalebi.BEKLEYEN).values("blok").distinct().count()
    return render(request, "program/ana.html", _baglam(
        request, gecerli=gecerli, surumler=surumler, bekleyen=bekleyen, devir_bekleyen=devir_bekleyen,
        bugun=timezone.localdate(),
    ))


def _yayin_engeli(s, baslangic, onceki_baslangic, onceki_durum):
    """Geçmiş günlerin programı (yapılmış sayılan dersler) ve devir görmüş dersler sonradan değişmez."""
    from takip.servis import yayin_engeli

    if onceki_durum == ProgramSurumu.YAYINDA and baslangic == onceki_baslangic:
        return None  # sadece bitiş/açıklama güncelleniyor
    baska_yayin = ProgramSurumu.objects.filter(durum=ProgramSurumu.YAYINDA).exclude(pk=s.pk).exists()
    if baska_yayin and baslangic < timezone.localdate():
        return "Yayında başka bir program varken başlangıç bugünden önce olamaz (geçmiş günlerin programı değişmesin)."
    return yayin_engeli(baslangic)


@yetki_gerekli(BIRIM)
def tablo(request):
    surum_id = request.GET.get("surum")
    if surum_id and surum_id.isdigit():
        surum = get_object_or_404(ProgramSurumu, pk=surum_id)
    else:
        surum = ProgramSurumu.objects.gecerli() or ProgramSurumu.objects.first()
    if surum is None:
        messages.info(request, "Henüz yüklenmiş bir program yok.")
        return redirect("program:ana")

    tur = request.GET.get("tur", "kisim")
    secim = request.GET.get("id", "")
    kisimlar = sorted(Kisim.objects.filter(haftalik_dersler__surum=surum).distinct(), key=lambda k: (k.sira_no == 0, k.sira_no, k.kod))
    ogretmenler = (ProgramOgretmeni.objects.filter(haftalik_dersler__surum=surum).exclude(durum=ProgramOgretmeni.YOK_SAY)
                   .select_related("personel").distinct())
    ogretmenler = sorted(ogretmenler, key=lambda o: str(o))
    derslikler = Derslik.objects.filter(hucreler__surum=surum).distinct().order_by("ad")

    hucreler = ProgramHucresi.objects.filter(surum=surum)
    secili = None
    if tur == "ogretmen":
        secili = next((o for o in ogretmenler if str(o.pk) == secim), None) or (ogretmenler[0] if ogretmenler else None)
        hucreler = hucreler.filter(haftalik_ders__ogretmenler=secili)
    elif tur == "derslik":
        secili = next((d for d in derslikler if str(d.pk) == secim), None) or derslikler.first()
        hucreler = hucreler.filter(derslik=secili)
    else:
        tur = "kisim"
        secili = next((k for k in kisimlar if str(k.pk) == secim), None) or (kisimlar[0] if kisimlar else None)
        hucreler = hucreler.filter(haftalik_ders__kisimlar=secili)

    hucreler = hucreler.select_related("haftalik_ders__ders__bolum", "derslik").prefetch_related(
        "haftalik_ders__ogretmenler__personel", "haftalik_ders__gruplar", "haftalik_ders__kisimlar",
    )
    gun_nolari = sorted(set(ProgramHucresi.objects.filter(surum=surum).values_list("gun", flat=True))) or [1, 2, 3, 4, 5]
    gunler = [(no, ad) for no, ad in GUNLER if no in gun_nolari]
    saatler = list(surum.ders_saatleri.all())
    izgara = {}
    for h in hucreler:
        d = h.haftalik_ders.ders
        h.zemin, h.kenar = _renk(d.bolum.kod if d.bolum_id else d.kod[:3])
        izgara.setdefault((h.gun, h.saat), []).append(h)
    satirlar = [(s, [izgara.get((g, s.no), []) for g, _ in gunler]) for s in saatler]

    return render(request, "program/tablo.html", _baglam(
        request, surum=surum, surumler=ProgramSurumu.objects.exclude(durum=ProgramSurumu.ARSIV),
        tur=tur, secili=secili, kisimlar=kisimlar, ogretmenler=ogretmenler, derslikler=derslikler,
        gunler=gunler, satirlar=satirlar, toplam_saat=len(hucreler), breadcrumb_ek=True,
    ))


@yetki_gerekli(BIRIM, YONETIM)
def surumler(request):
    form = YuklemeForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        dosya = form.cleaned_data["dosya"]
        try:
            surum, rapor = ice_aktar(dosya, surum_adi=form.cleaned_data["ad"], kaynak_dosya=dosya.name, kullanici=request.user)
        except AscHatasi as e:
            form.add_error("dosya", str(e))
        else:
            request.session[f"asc_rapor_{surum.pk}"] = {"sayilar": rapor.sayilar, "uyarilar": rapor.uyarilar[:50]}
            messages.success(request, f"“{surum.ad}” taslak olarak yüklendi. Kontrol edip yayınlayabilirsiniz.")
            return redirect("program:surum", pk=surum.pk)
    liste = ProgramSurumu.objects.select_related("yukleyen", "yayinlayan").annotate(
        ders_sayisi=Count("dersler", distinct=True), hucre_sayisi=Count("hucreler", distinct=True),
    )
    return render(request, "program/surumler.html", _baglam(
        request, form=form, liste=liste, gecerli=ProgramSurumu.objects.gecerli(), breadcrumb_ek=True,
    ))


@yetki_gerekli(BIRIM, YONETIM)
def surum(request, pk):
    s = get_object_or_404(ProgramSurumu, pk=pk)
    onceki_baslangic, onceki_durum = s.baslangic, s.durum
    form = YayinForm(request.POST or None, instance=s)
    if request.method == "POST":
        islem = request.POST.get("islem")
        engel = None
        if islem == "yayinla" and form.is_valid():
            engel = _yayin_engeli(s, form.cleaned_data["baslangic"], onceki_baslangic, onceki_durum)
            if engel:
                form.add_error("baslangic", engel)
        if islem == "yayinla" and form.is_valid() and not engel:
            s = form.save(commit=False)
            s.durum, s.yayinlayan, s.yayin_zamani = ProgramSurumu.YAYINDA, request.user, timezone.now()
            s.save()
            bildirim.ders_programi(s, request.user)
            messages.success(request, f"“{s.ad}” {s.baslangic:%d.%m.%Y} tarihinden itibaren yayında.")
            return redirect("program:surum", pk=s.pk)
        if islem == "arsivle":
            from takip.models import DersKaydi
            if DersKaydi.objects.filter(hucre__surum=s).exists():
                messages.error(request, "Bu programın derslerinde devir kaydı var; arşive alınamaz.")
                return redirect("program:surum", pk=s.pk)
            s.durum = ProgramSurumu.ARSIV
            s.save(update_fields=["durum"])
            messages.info(request, f"“{s.ad}” arşive alındı.")
            return redirect("program:surumler")
        if islem == "sil" and s.durum == ProgramSurumu.TASLAK:
            ad = s.ad
            s.delete()
            messages.info(request, f"“{ad}” taslağı silindi.")
            return redirect("program:surumler")
    ozet = {
        "Haftalık ders": s.dersler.count(),
        "Yerleşmiş ders saati": s.hucreler.count(),
        "Kısım": Kisim.objects.filter(haftalik_dersler__surum=s).distinct().count(),
        "Öğretmen": ProgramOgretmeni.objects.filter(haftalik_dersler__surum=s).distinct().count(),
        "Derslikli saat": s.hucreler.exclude(derslik=None).count(),
    }
    bekleyen = ProgramOgretmeni.objects.filter(haftalik_dersler__surum=s, durum=ProgramOgretmeni.BEKLIYOR).distinct().count()
    return render(request, "program/surum.html", _baglam(
        request, s=s, form=form, ozet=ozet, bekleyen=bekleyen,
        rapor=request.session.get(f"asc_rapor_{s.pk}"), breadcrumb_ek=True,
    ))


@yetki_gerekli(BIRIM, YONETIM)
def ogretmenler(request):
    durum = request.GET.get("durum", ProgramOgretmeni.BEKLIYOR)
    q = request.GET.get("q", "").strip()
    qs = ProgramOgretmeni.objects.select_related("personel__bolum", "tahmini_bolum").annotate(
        ders_sayisi=Count("haftalik_dersler", distinct=True),
    )
    if durum in dict(ProgramOgretmeni.DURUM_SECENEKLERI):
        qs = qs.filter(durum=durum)
    if q:
        qs = ara(qs, q, "ad", "personel__ad_soyad")
    liste = list(qs)
    oneri = eslestirme.oneriler([o for o in liste if o.durum == ProgramOgretmeni.BEKLIYOR])
    for o in liste:
        o.oneri, oran = oneri.get(o.pk, (None, 0))
        o.benzerlik = round(oran * 100)
    sayilar = dict(ProgramOgretmeni.objects.values_list("durum").annotate(n=Count("pk")))
    sekmeler = [(kod, ad, sayilar.get(kod, 0)) for kod, ad in ProgramOgretmeni.DURUM_SECENEKLERI]
    bagli = ProgramOgretmeni.objects.exclude(personel=None).values_list("personel_id", flat=True)
    return render(request, "program/ogretmenler.html", _baglam(
        request, liste=liste, durum=durum, q=q, sekmeler=sekmeler,
        bos_personel=Personel.objects.filter(derse_girebilir=True).exclude(pk__in=bagli).select_related("bolum").order_by("ad_soyad"),
        onerisiz=sum(1 for o in liste if o.durum == ProgramOgretmeni.BEKLIYOR and not o.oneri),
        breadcrumb_ek=True,
    ))


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def ogretmen_islem(request, pk):
    o = get_object_or_404(ProgramOgretmeni, pk=pk)
    islem = request.POST.get("islem")
    if islem == "eslestir":
        p = get_object_or_404(Personel, pk=request.POST.get("personel"))
        eslestirme.eslestir(o, p)
        messages.success(request, f"{o.ad} → {p.ad_soyad} olarak eşleştirildi.")
    elif islem == "yeni":
        eslestirme.yeni_personel_olarak_ekle(o)
        messages.success(request, f"{o.ad} yeni personel olarak eklendi.")
    elif islem == "yoksay":
        eslestirme.yok_say(o)
        messages.info(request, f"{o.ad} yok sayıldı.")
    elif islem == "geri_al":
        eslestirme.geri_al(o)
        messages.info(request, f"{o.ad} için eşleşme kaldırıldı.")
    return redirect(request.POST.get("geri") or "program:ogretmenler")


@require_POST
@yetki_gerekli(BIRIM, YONETIM)
def ogretmen_toplu(request):
    bekleyen = ProgramOgretmeni.objects.filter(durum=ProgramOgretmeni.BEKLIYOR).select_related("tahmini_bolum")
    eklenen, onerili = eslestirme.onerisizleri_toplu_ekle(list(bekleyen))
    messages.success(request, f"{eklenen} öğretmen yeni personel olarak eklendi."
                     + (f" Benzer personel önerisi olan {onerili} kayıt sizin kararınızı bekliyor." if onerili else ""))
    return redirect("program:ogretmenler")
