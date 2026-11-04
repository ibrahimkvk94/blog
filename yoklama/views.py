import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum

from . import foto, servis
from .models import RENKLER, GunlukOnay, IzinTuru, YoklamaGecmisi, YoklamaKaydi
from .servis import YoklamaHatasi


def _baglam(request, **ek):
    request.birim = birim_bul(request, servis.BIRIM)
    bugun = timezone.localdate()
    taban = {"yol": yol(request, request.birim), "y": servis.yetki(request), "breadcrumb_ek": True, "bugun": bugun,
             "hafta": bugun + datetime.timedelta(days=6)}
    return {**taban, **ek}


def _goruntule(request):
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    return y


def _yonetim(request):
    y = servis.yetki(request)
    if not y.yonetim:
        raise PermissionDenied
    return y


def _tarih(metin, varsayilan=None):
    try:
        return datetime.date.fromisoformat(str(metin))
    except (TypeError, ValueError):
        return varsayilan


def _saat(metin):
    try:
        return datetime.time.fromisoformat(str(metin))
    except (TypeError, ValueError):
        return None


def _geri(request, varsayilan):
    hedef = request.POST.get("geri") or request.GET.get("geri")
    if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        return redirect(hedef)
    return redirect(varsayilan)


def _secili_bolum(request, y):
    if y.kapsam_bolum is not None:
        return y.kapsam_bolum
    pk = request.GET.get("bolum", "")
    return Bolum.objects.filter(pk=pk).first() if pk.isdigit() else None


def _kayit_formu(request):
    """POST'tan (tür, başlangıç, bitiş, açıklama); hatalıysa YoklamaHatasi."""
    tur = IzinTuru.objects.filter(pk=request.POST.get("tur") or 0).first()
    tam_gun = request.POST.get("bicim", "tam") == "tam"
    bas_tarih = _tarih(request.POST.get("bas_tarih"))
    if tam_gun:
        bas, bit = servis.aralik(True, bas_tarih, _tarih(request.POST.get("bit_tarih"), bas_tarih))
    else:
        bas, bit = servis.aralik(False, bas_tarih, bas_tarih, _saat(request.POST.get("bas_saat")),
                                 _saat(request.POST.get("bit_saat")))
    return tur, bas, bit, request.POST.get("aciklama", "")


# ---------------------------------------------------------------- yoklama (gün / aralık)

@login_required
def ana(request):
    y = _goruntule(request)
    bugun = timezone.localdate()
    bolum = _secili_bolum(request, y)
    kisiler = list(servis.personeller(y, bolum))
    bas = _tarih(request.GET.get("bas"))
    bit = _tarih(request.GET.get("bit"))
    ctx = {"bugun": bugun, "dun": bugun - datetime.timedelta(days=1), "yarin": bugun + datetime.timedelta(days=1),
           "secili_bolum": bolum, "bolumler": servis.bolumler(y) if y.kapsam_bolum is None else [],
           "turler": servis.izin_turleri(), "breadcrumb_ek": False}
    if bas and bit and bit != bas:  # aralık görünümü
        if bit < bas:
            bas, bit = bit, bas
        if (bit - bas).days >= servis.EN_UZUN_ARALIK:
            bit = bas + datetime.timedelta(days=servis.EN_UZUN_ARALIK - 1)
            messages.info(request, f"Aralık en fazla {servis.EN_UZUN_ARALIK} gün gösterilir.")
        hepsi = request.GET.get("hepsi") == "1"
        gunler, satirlar, gun_ozet = servis.takvim(bas, bit, kisiler, hepsi)
        return render(request, "yoklama/aralik.html", _baglam(
            request, **ctx, bas=bas, bit=bit, gunler=gunler, satirlar=satirlar, gun_ozet=gun_ozet, hepsi=hepsi,
            toplam=len(kisiler)))
    tarih = _tarih(request.GET.get("tarih"), bas or bugun)
    durumlar = servis.gun_durumu(tarih, kisiler)
    filtre = request.GET.get("durum", "")
    secim = {"yok": lambda d: not d.mevcut, "gun_boyu": lambda d: d.gun_boyu, "kismi": lambda d: d.kismi,
             "mevcut": lambda d: d.mevcut}.get(filtre)
    gorunen = [d for d in durumlar if secim(d)] if secim else durumlar
    onay = onay_tablo = None
    if y.kapsam_bolum is not None:
        onay = GunlukOnay.objects.filter(bolum=y.kapsam_bolum, tarih=tarih).select_related("onaylayan").first()
    elif bolum is not None:
        onay = GunlukOnay.objects.filter(bolum=bolum, tarih=tarih).select_related("onaylayan").first()
    else:
        onay_tablo = servis.onay_tablosu(tarih, servis.bolumler(y))
    onay_bolumu = y.kapsam_bolum or bolum
    return render(request, "yoklama/gun.html", _baglam(
        request, **ctx, tarih=tarih, durumlar=gorunen, ozet=servis.ozet(durumlar), filtre=filtre, onay=onay,
        onay_tablo=onay_tablo, onay_bolumu=onay_bolumu,
        onaylayabilir=bool(onay_bolumu) and servis.onay_yetkisi(y, onay_bolumu),
        onceki=tarih - datetime.timedelta(days=1), sonraki=tarih + datetime.timedelta(days=1)))


@require_POST
@login_required
def onay(request):
    y = servis.yetki(request)
    bolum = y.kapsam_bolum or get_object_or_404(Bolum, pk=request.POST.get("bolum") or 0)
    tarih = _tarih(request.POST.get("tarih"), timezone.localdate())
    try:
        servis.onayla(request.user, y, bolum, tarih)
    except YoklamaHatasi as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{bolum.ad}: {tarih:%d.%m.%Y} yoklaması verildi.")
    return _geri(request, f"{reverse('yoklama:ana')}?tarih={tarih.isoformat()}")


# ---------------------------------------------------------------- personel kartı

@login_required
def kart(request, pk):
    y = _goruntule(request)
    p = servis.kapsamdaki_personel(y, pk)
    bugun = timezone.localdate()
    if request.method == "POST":
        if not y.giris or not y.kapsar(p.bolum_id):
            raise PermissionDenied
        try:
            tur, bas, bit, aciklama = _kayit_formu(request)
            k = servis.ekle(request.user, y, p, tur, bas, bit, aciklama)
        except YoklamaHatasi as e:
            messages.error(request, str(e))
            return _geri(request, reverse("yoklama:kart", args=[p.pk]))
        messages.success(request, f"{p.ad_soyad}: {k.tur.ad} kaydedildi ({k.aralik_metni}).")
        return _geri(request, reverse("yoklama:kart", args=[p.pk]))
    yil = int(request.GET.get("yil") or bugun.year)
    simdi = timezone.now()
    tum = list(p.yoklama_kayitlari.select_related("tur", "olusturan", "guncelleyen"))
    gelecek = [k for k in tum if k.bitis > simdi]
    gecmis = [k for k in tum if k.bitis <= simdi and k.yerel_bas.year == yil]
    yil_ozeti = {}
    for k in tum:
        if k.yerel_bas.year == yil:
            o = yil_ozeti.setdefault(k.tur_id, {"tur": k.tur, "gun": 0, "saat": 0.0, "adet": 0})
            o["adet"] += 1
            if k.tam_gun:
                o["gun"] += k.gun_sayisi
            else:
                o["saat"] += (k.bitis - k.baslangic).total_seconds() / 3600
    bugun_durum = servis.gun_durumu(bugun, [p])[0]
    yillar = sorted({k.yerel_bas.year for k in tum} | {bugun.year}, reverse=True)
    return render(request, "yoklama/kart.html", _baglam(
        request, p=p, bugun=bugun, bugun_durum=bugun_durum, gelecek=gelecek, gecmis=gecmis, yil=yil, yillar=yillar,
        yil_ozeti=sorted(yil_ozeti.values(), key=lambda o: (o["tur"].sira, o["tur"].ad)),
        turler=servis.izin_turleri(), girebilir=y.giris and y.kapsar(p.bolum_id),
        islemler=list(p.yoklama_gecmisi.select_related("kullanici")[:15]),
        varsayilan_tarih=_tarih(request.GET.get("tarih"), bugun)))


@login_required
def kayit(request, pk):
    """Kaydı düzenle / sil."""
    y = _goruntule(request)
    k = get_object_or_404(YoklamaKaydi.objects.select_related("personel", "tur"), pk=pk)
    p = servis.kapsamdaki_personel(y, k.personel_id)
    kart_url = reverse("yoklama:kart", args=[p.pk])
    if request.method == "POST":
        try:
            if request.POST.get("islem") == "sil":
                servis.sil(request.user, y, k.pk)
                messages.success(request, "Kayıt silindi.")
                return redirect(kart_url)
            tur, bas, bit, aciklama = _kayit_formu(request)
            servis.duzenle(request.user, y, k.pk, int(request.POST.get("surum") or 0), tur, bas, bit, aciklama)
        except YoklamaHatasi as e:
            messages.error(request, str(e))
            return redirect(request.path)
        messages.success(request, "Kayıt güncellendi.")
        return redirect(kart_url)
    return render(request, "yoklama/kayit.html", _baglam(
        request, k=k, p=p, turler=IzinTuru.objects.filter(aktif=True) | IzinTuru.objects.filter(pk=k.tur_id),
        girebilir=y.giris and y.kapsar(p.bolum_id)))


# ---------------------------------------------------------------- fotoğraf

@login_required
def fotograf(request, pk):
    y = _goruntule(request)
    p = servis.kapsamdaki_personel(y, pk)
    if not p.fotograf:
        raise Http404
    try:
        yanit = FileResponse(p.fotograf.open("rb"), content_type="image/jpeg")
    except FileNotFoundError:
        raise Http404 from None
    yanit["Cache-Control"] = "private, max-age=3600"
    return yanit


@require_POST
@login_required
def fotograf_yukle(request, pk):
    y = _goruntule(request)
    p = servis.kapsamdaki_personel(y, pk)
    if not y.giris or not y.kapsar(p.bolum_id):
        raise PermissionDenied
    if request.POST.get("islem") == "kaldir":
        foto.kaldir(p)
        messages.success(request, "Fotoğraf kaldırıldı.")
    else:
        dosya = request.FILES.get("fotograf")
        if not dosya:
            messages.error(request, "Fotoğraf seçin.")
        else:
            try:
                foto.kaydet(p, dosya.read())
            except foto.FotoHatasi as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Fotoğraf güncellendi.")
    return redirect("yoklama:kart", pk=p.pk)


class _ZipFormu(forms.Form):
    dosya = forms.FileField()


@login_required
def toplu_fotograf(request):
    y = _yonetim(request)
    sonuc = None
    if request.method == "POST":
        form = _ZipFormu(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Zip dosyası seçin.")
        else:
            try:
                yuklenen, eslesmeyen, hatali = foto.toplu(form.cleaned_data["dosya"], list(servis.personeller(y)))
            except foto.FotoHatasi as e:
                messages.error(request, str(e))
            else:
                sonuc = {"yuklenen": yuklenen, "eslesmeyen": eslesmeyen, "hatali": hatali}
    kisiler = servis.personeller(y)
    return render(request, "yoklama/toplu_fotograf.html", _baglam(
        request, sonuc=sonuc, fotolu=kisiler.exclude(fotograf="").count(), toplam=kisiler.count()))


# ---------------------------------------------------------------- izin türleri

class TurFormu(forms.ModelForm):
    class Meta:
        model = IzinTuru
        fields = ["ad", "kisa", "renk", "sira", "aktif", "aciklama"]


@login_required
def turler(request):
    _yonetim(request)
    duzenlenen = IzinTuru.objects.filter(pk=request.GET.get("duzenle") or 0).first()
    form = TurFormu(instance=duzenlenen)
    if request.method == "POST":
        if request.POST.get("islem") == "sil":
            t = get_object_or_404(IzinTuru, pk=request.POST.get("pk") or 0)
            if t.kayitlar.exists():
                messages.error(request, f"“{t.ad}” kullanılmış ({t.kayitlar.count()} kayıt); silinemez. Kapatabilirsiniz.")
            else:
                t.delete()
                messages.success(request, f"“{t.ad}” silindi.")
            return redirect("yoklama:turler")
        duzenlenen = IzinTuru.objects.filter(pk=request.POST.get("pk") or 0).first()
        form = TurFormu(request.POST, instance=duzenlenen)
        if form.is_valid():
            t = form.save()
            messages.success(request, f"“{t.ad}” kaydedildi.")
            return redirect("yoklama:turler")
    for alan in form.fields.values():
        alan.widget.attrs.setdefault("class", "form-select" if isinstance(alan.widget, forms.Select) else "form-control")
    form.fields["aktif"].widget.attrs["class"] = "form-check-input"
    return render(request, "yoklama/turler.html", _baglam(
        request, turler=IzinTuru.objects.annotate(kullanim=Count("kayitlar")), form=form, duzenlenen=duzenlenen,
        renkler=RENKLER))


# ---------------------------------------------------------------- rapor

@login_required
def rapor(request):
    y = _goruntule(request)
    bugun = timezone.localdate()
    bas = _tarih(request.GET.get("bas"), bugun.replace(day=1))
    bit = _tarih(request.GET.get("bit"), bugun)
    if bit < bas:
        bas, bit = bit, bas
    if (bit - bas).days >= 366:
        bit = bas + datetime.timedelta(days=365)
    bolum = _secili_bolum(request, y)
    from .rapor import excel

    return excel(bas, bit, list(servis.personeller(y, bolum)), bolum)


@login_required
def gecmis(request):
    y = _goruntule(request)
    qs = YoklamaGecmisi.objects.select_related("personel__bolum", "kullanici")
    if y.kapsam_bolum is not None:
        qs = qs.filter(personel__bolum=y.kapsam_bolum)
    if request.GET.get("onay_sonrasi") == "1":
        qs = qs.filter(onay_sonrasi=True)
    return render(request, "yoklama/gecmis.html", _baglam(request, islemler=list(qs[:300]),
                                                          onay_sonrasi=request.GET.get("onay_sonrasi") == "1"))
