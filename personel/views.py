"""Personel Kartları.

Yetki ("Personel Kartları" birimi):
- Görüntüleme / düzenleme: temel bilgiler (ad, sicil, bölüm, rütbe, sınıf, unvan) yetkisi kadar. Kapsamı "kendi
  bölümü" olan hesap yalnız kendi teşkilat birimini (bölüm, şube müdürlüğü, kısım …) ve alt birimlerini görür;
  tüm okulu "tüm bölümler" kapsamındakiler görür. T.C. kimlik no gizlidir.
- Yönetim (yönetici): T.C. kimlik no, ek kart alanları (telefon, adres …), fotoğraf, ders / sınav kullanımı,
  teşkilattaki yeri, görev unvanı, idari kadro ve bölüm başkanlığı; kart alanlarını ve teşkilat şemasını yönetir.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, ProtectedError, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import Yetki
from core.yetki import DUZENLEME, YONETIM, yetki_gerekli, yol

from core.arama import ara

from . import kart
from .forms import KartAlaniFormu, PersonelForm, TeskilatFormu
from yoklama.birim import BIRIMSIZ, Agac

from .models import Bolum, KartAlani, KartDegeri, Personel, Secenek, TeskilatBirimi

BIRIM = "personel-bilgileri"


def _agac(request):
    if not hasattr(request, "_pk_agac"):
        request._pk_agac = Agac()
    return request._pk_agac


def _kapsam(request):
    """(kapsam birimi, kimlikler) — tüm okulda (None, None)."""
    agac = _agac(request)
    if request.yetki_kapsam == Yetki.BOLUM:
        u = request.user
        b = agac.birimler.get(u.teskilat_birimi_id) or agac.bolumun(u.bolum_id)
        return (b, agac.alt_idler(b.pk)) if b else (None, set())
    return None, None


def _kapsamli(request):
    qs = Personel.objects.select_related("bolum", "rutbe", "sinif", "unvan", "teskilat_birimi")
    _, idler = _kapsam(request)
    if idler is None:
        return qs
    return qs.filter(_agac(request).kosul(idler)) if idler else qs.none()


def _sabit_bolum(request):
    if request.yetki_kapsam != Yetki.BOLUM or request.user.teskilat_birimi_id:
        return None
    return request.user.bolum


def _sabit_birim(request):
    """Şube müdürlüğü / kısım hesabının birimi (eklediği personel oraya yazılır)."""
    if request.yetki_kapsam != Yetki.BOLUM:
        return None
    return _agac(request).birimler.get(request.user.teskilat_birimi_id)


def _yonetici(request):
    return request.yetki_seviye >= YONETIM


def _baglam(request, **ek):
    return {"yol": yol(request, request.birim), "yonetici": _yonetici(request),
            "duzenleyebilir": request.yetki_seviye >= DUZENLEME, **ek}


def _secili_birim(request):
    agac = _agac(request)
    kapsam_birim, idler = _kapsam(request)
    pk = request.GET.get("birim", "")
    b = None
    if pk.isdigit():
        b = agac.get(int(pk))
        if b is BIRIMSIZ and idler is not None:
            b = None
    elif request.GET.get("bolum", "").isdigit():
        b = agac.bolumun(int(request.GET["bolum"]))
    if b is not None and b.pk and idler is not None and b.pk not in idler:
        b = None
    return b if b is not None else kapsam_birim


def _liste_verisi(request):
    """Liste ve Excel için ortak süzme: kapsam, birim, arama, durum, rütbe, eksik."""
    agac = _agac(request)
    yonetici = _yonetici(request)
    birim = _secili_birim(request)
    q = request.GET.get("q", "").strip()
    rutbe = request.GET.get("rutbe", "")
    durum = request.GET.get("durum", "aktif")
    yalniz_eksik = yonetici and request.GET.get("eksik") == "1"
    qs = _kapsamli(request)
    if durum == "aktif":
        qs = qs.filter(aktif=True)
    elif durum == "pasif":
        qs = qs.filter(aktif=False)
    if rutbe.isdigit():
        qs = qs.filter(rutbe_id=rutbe)
    tum = list(qs.order_by("ad_soyad"))
    if birim is not None and (q or yalniz_eksik):  # arama ve eksikler birimin altını da kapsar
        idler = agac.alt_idler(birim.pk) if birim.pk else {0}
        tum = [x for x in tum if agac.kisi_birimi(x) in idler]
    if q:  # Türkçe harf / büyük-küçük harf duyarsız; kimlik no ile arama yalnız yöneticide
        alanlar = ["ad_soyad", "sicil", "gorev_unvani"] + (["personel_kodu"] if yonetici else [])
        bulunan = set(ara(qs, q, *alanlar).values_list("pk", flat=True))
        tum = [x for x in tum if x.pk in bulunan]
    eksikmap = kart.eksikler(tum) if yonetici else None
    if yalniz_eksik:
        tum = [x for x in tum if eksikmap.get(x.pk)]
    for x in tum:
        x.liste_birimi = agac.get(agac.kisi_birimi(x))
        x.eksik_listesi = eksikmap.get(x.pk, []) if eksikmap else []
    return {"birim": birim, "q": q, "rutbe": rutbe, "durum": durum, "yalniz_eksik": yalniz_eksik, "kisiler": tum,
            "eksikmap": eksikmap}


@yetki_gerekli(BIRIM)
def liste(request):
    """Tüm okul: teşkilata göre birim kutucukları. Birim seçilince (ya da birim hesabında) o birimin kart vitrini
    (ya da tablo); arama yazdıkça tüm kapsamda eşleşenler."""
    from yoklama.servis import bolumle

    agac = _agac(request)
    kapsam_birim, idler = _kapsam(request)
    v = _liste_verisi(request)
    birim, kisiler = v["birim"], v["kisiler"]
    gorunum = "tablo" if request.GET.get("gorunum") == "tablo" else "vitrin"
    kip = "arama" if (v["q"] or v["yalniz_eksik"]) else ("genel" if birim is None else "birim")
    ctx = dict(v, gorunum=gorunum, kip=kip, sekme="liste",
               rutbeler=Secenek.objects.filter(tur=Secenek.RUTBE, aktif=True),
               birim_secenekleri=[(b, d) for b, d in agac.sirali([kapsam_birim.pk] if kapsam_birim else None)],
               tum_okul=idler is None,
               birim_zinciri=[b for b in agac.zincir(birim.pk) if (idler is None or b.pk in idler) and b != birim]
               if birim is not None and birim.pk else [])
    if kip == "genel":
        ctx["gruplar"] = bolumle(kart.birim_ozetleri(agac, kisiler, None, v["eksikmap"]))
        ctx["toplam"] = len(kisiler)
        ctx["fotosuz"] = sum(1 for x in kisiler if not x.fotograf)
        ctx["eksik_sayi"] = sum(1 for x in kisiler if x.eksik_listesi) if v["eksikmap"] is not None else None
    elif kip == "birim":
        alt_idler = agac.alt_idler(birim.pk) if birim.pk else {0}
        alttakiler = [x for x in kisiler if agac.kisi_birimi(x) in alt_idler]
        ctx["alt_birimler"] = [o for o in kart.birim_ozetleri(agac, alttakiler, [birim.pk], v["eksikmap"], haric=birim)
                               if o["toplam"]] if birim.pk else []
        ctx["kisiler"] = kart.yetki_sirali([x for x in alttakiler if agac.kisi_birimi(x) == birim.pk], birim)
        ctx["toplam"] = len(ctx["kisiler"])
        ctx["fotosuz"] = sum(1 for x in ctx["kisiler"] if not x.fotograf)
        ctx["eksik_sayi"] = sum(1 for x in ctx["kisiler"] if x.eksik_listesi) if v["eksikmap"] is not None else None
        ctx["sorumlu"] = (birim.bolum.baskan if getattr(birim, "bolum_id", None) and birim.bolum.baskan_id else
                          kart.sorumlu_sec(ctx["kisiler"]))
    else:
        ctx["toplam"] = len(kisiler)
        ctx["kisiler"] = kisiler[:300]
    return render(request, "personel/liste.html", _baglam(request, **ctx))


@yetki_gerekli(BIRIM)
def excel(request):
    """Ekrandaki süzmeyle personel listesi (Excel). Kimlik no ve kart alanları yalnız yöneticide."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    v = _liste_verisi(request)
    yonetici = _yonetici(request)
    kisiler = v["kisiler"]
    if v["birim"] is not None and not (v["q"] or v["yalniz_eksik"]):
        idler = _agac(request).alt_idler(v["birim"].pk) if v["birim"].pk else {0}
        kisiler = [x for x in kisiler if _agac(request).kisi_birimi(x) in idler]
    alanlar = list(KartAlani.objects.filter(aktif=True)) if yonetici else []
    degerler = {}
    if alanlar:
        for d in KartDegeri.objects.filter(personel__in=[x.pk for x in kisiler], alan__in=alanlar):
            degerler[(d.personel_id, d.alan_id)] = kart.gosterim(d.alan, d.deger)
    wb = Workbook()
    ws = wb.active
    ws.title = "Personel"
    basliklar = ["Ad soyad", "Künye", "Sicil no", "Birim", "Kadro görevi", "Branş", "Bölüm"]
    if yonetici:
        basliklar += ["T.C. kimlik no"] + [a.ad for a in alanlar] + ["Eksik bilgiler"]
    ws.append(basliklar)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for x in kisiler:
        satir = [x.ad_soyad, x.kunye, x.sicil, getattr(x.liste_birimi, "ad", ""), x.kadro_gorevi,
                 x.brans, x.bolum.ad if x.bolum_id else ""]
        if yonetici:
            satir += [x.personel_kodu or ""] + [degerler.get((x.pk, a.pk), "") for a in alanlar] + [
                ", ".join(x.eksik_listesi)]
        ws.append(satir)
    for i, en in enumerate([26, 22, 12, 30, 28, 16, 26] + ([14] + [18] * len(alanlar) + [30] if yonetici else []), 1):
        ws.column_dimensions[get_column_letter(i)].width = en
    ws.freeze_panes = "B2"
    cevap = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    ad = "personel_kartlari" + (f"_birim{v['birim'].pk}" if v["birim"] is not None else "")
    cevap["Content-Disposition"] = f'attachment; filename="{ad}.xlsx"'
    wb.save(cevap)
    return cevap


@yetki_gerekli(BIRIM)
def detay(request, pk):
    p = get_object_or_404(_kapsamli(request), pk=pk)
    yonetici = _yonetici(request)
    return render(request, "personel/detay.html", _baglam(
        request, p=p, breadcrumb_ek=True, teskilat_yeri=kart.teskilattaki_yeri(p),
        kart_bilgileri=kart.kart_bilgileri(p, sadece_dolu=False) if yonetici else [],
        baskan_mi=bool(p.bolum_id and p.bolum.baskan_id == p.pk), **_izin_haklari(p)))


def _izin_haklari(p):
    from yoklama import servis as yoklama_servis

    yil = timezone.localdate().year
    return {"izin_yili": yil, "izin_haklari": yoklama_servis.izin_haklari(p, yil)}


@yetki_gerekli(BIRIM, DUZENLEME)
def ekle(request):
    return _form(request, None)


@yetki_gerekli(BIRIM, DUZENLEME)
def duzenle(request, pk):
    return _form(request, get_object_or_404(_kapsamli(request), pk=pk))


def _form(request, nesne):
    yonetici = _yonetici(request)
    sabit_birim = _sabit_birim(request)
    form = PersonelForm(request.POST or None, instance=nesne, sabit_bolum=_sabit_bolum(request), yonetici=yonetici,
                        bolumsuz_olur=yonetici or sabit_birim is not None)
    if request.method == "POST" and form.is_valid():
        eski_sinav = nesne.sinav_gorevi_alabilir if nesne else True
        p = form.save()
        if sabit_birim is not None and p.teskilat_birimi_id is None and not p.bolum_id:
            p.teskilat_birimi = sabit_birim  # şube / kısım hesabının eklediği personel kendi birimine
            p.save(update_fields=["teskilat_birimi"])
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
            if not ids:
                messages.warning(request, "Atanacak personel seçilmedi; hiçbir değişiklik yapılmadı.")
                return redirect("personel:teskilat_birimi", pk=b.pk)
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
    _, idler = _kapsam(request)
    if idler is not None:  # kendi bölümü / birimi kapsamlı hesap: yalnız kapsamındaki personel (kartı da açılabilen)
        agac = _agac(request)
        kisiler = [p for p in kisiler if agac.kisi_birimi(p) in idler]
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
