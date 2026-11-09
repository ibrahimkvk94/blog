import datetime

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F
from urllib.parse import quote

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol
from personel.models import Bolum

from . import foto, servis
from .models import (OGLEDEN_ONCE, OGLEDEN_SONRA, RENKLER, GunlukOnay, IzinTuru, PersonelGrubu, YoklamaGecmisi,
                     YoklamaKaydi)
from .birim import BIRIMSIZ
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


def _guvenli_geri(request):
    hedef = request.POST.get("geri") or request.GET.get("geri") or ""
    return hedef if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}) else ""


def _secili_birim(request, y, varsayilan=True):
    """?birim=<kimlik> (eski bağlantılar: ?bolum=<kimlik>). Kapsam dışı birim seçilemez. Seçilmezse hesabın kendi
    birimi; tüm okulu görenlerde None (genel görünüm)."""
    agac = y.agac
    pk = request.POST.get("birim") or request.GET.get("birim") or ""
    b = None
    if pk.isdigit():
        b = agac.get(int(pk))
        if b is BIRIMSIZ and not y.tum_okul:
            b = None
    elif (request.GET.get("bolum") or "").isdigit():
        b = agac.bolumun(int(request.GET["bolum"]))
    if b is not None and b.pk and not y.kapsar_birim(b.pk):
        b = None
    if b is None and varsayilan:
        b = y.kapsam_birim
    return b


def _birim_q(birim):
    return f"&birim={birim.pk}" if birim is not None else ""


def _birim_sayfasi(y, p, tarih):
    """Personelin birim yoklama sayfası (kayıttan sonra dönülür)."""
    return f"{reverse('yoklama:ana')}?tarih={tarih.isoformat()}&birim={y.agac.kisi_birimi(p)}"


def _kayit_formu(request):
    """POST'tan (tür, başlangıç, bitiş, açıklama); hatalıysa YoklamaHatasi."""
    tur = IzinTuru.objects.filter(pk=request.POST.get("tur") or 0).first()
    bicim = request.POST.get("bicim", "tam")
    tam_gun = bicim == "tam"
    bas_tarih = _tarih(request.POST.get("bas_tarih"))
    if tam_gun:
        bas, bit = servis.aralik(True, bas_tarih, _tarih(request.POST.get("bit_tarih"), bas_tarih))
    elif bicim in ("oo", "os"):  # öğleden önce / sonra: sabit saatler
        bas, bit = servis.aralik(False, bas_tarih, bas_tarih, *(OGLEDEN_ONCE if bicim == "oo" else OGLEDEN_SONRA))
    else:
        bas, bit = servis.aralik(False, bas_tarih, bas_tarih, _saat(request.POST.get("bas_saat")),
                                 _saat(request.POST.get("bit_saat")))
    return tur, bas, bit, request.POST.get("aciklama", "")


# ---------------------------------------------------------------- yoklama (gün / aralık)

@login_required
def ana(request):
    """Tüm okulu görenler: teşkilata göre birim kutucukları (genel görünüm). Birim seçilince (ya da birim hesabında):
    o birimin kendi personeli, kesinleştirme ve alt birimleri."""
    y = _goruntule(request)
    agac = y.agac
    bugun = timezone.localdate()
    birim = _secili_birim(request, y)
    bas = _tarih(request.GET.get("bas"))
    bit = _tarih(request.GET.get("bit"))
    secenekler = servis.birim_secenekleri(y)
    ctx = {"bugun": bugun, "dun": bugun - datetime.timedelta(days=1), "yarin": bugun + datetime.timedelta(days=1),
           "secili_birim": birim, "birim_q": _birim_q(birim), "birim_secenekleri": secenekler if len(secenekler) > 1 else [],
           "turler": servis.izin_turleri(), "breadcrumb_ek": False,
           "birim_zinciri": [b for b in agac.zincir(birim.pk) if y.kapsar_birim(b.pk) and b != birim] if birim and birim.pk else []}
    if bas and bit and bit != bas:  # aralık görünümü
        if bit < bas:
            bas, bit = bit, bas
        if (bit - bas).days >= servis.EN_UZUN_ARALIK:
            bit = bas + datetime.timedelta(days=servis.EN_UZUN_ARALIK - 1)
            messages.info(request, f"Aralık en fazla {servis.EN_UZUN_ARALIK} gün gösterilir.")
        kisiler = list(servis.personeller(y, birim))
        for k in kisiler:
            k.yoklama_birimi = agac.get(agac.kisi_birimi(k))
        hepsi = request.GET.get("hepsi") == "1"
        gunler, satirlar, gun_ozet = servis.takvim(bas, bit, kisiler, hepsi)
        return render(request, "yoklama/aralik.html", _baglam(
            request, **ctx, bas=bas, bit=bit, gunler=gunler, satirlar=satirlar, gun_ozet=gun_ozet, hepsi=hepsi,
            toplam=len(kisiler), cok_birim=birim is None or bool(agac.cocuklar.get(birim.pk))))
    tarih = _tarih(request.GET.get("tarih"), bas or bugun)
    ilk_giris = None if y.yonetim else servis.ilk_giris_tarihi()
    ctx.update(tarih=tarih, onceki=tarih - datetime.timedelta(days=1), sonraki=tarih + datetime.timedelta(days=1),
               ilk_giris=ilk_giris, modal_tarih=max(tarih, ilk_giris) if ilk_giris else tarih)

    if birim is None:  # tüm okul: birim kutucukları ve kişi arama
        kisiler = list(servis.personeller(y))
        durumlar = servis.gun_durumu(tarih, kisiler)
        ozetler = servis.birim_ozetleri(y, tarih)
        q = request.GET.get("q", "").strip()
        bulunan = []
        if q:
            from core.arama import eslesir

            bulunan = [d for d in durumlar if eslesir(q, d.personel.ad_soyad, d.personel.sicil)][:40]
            for d in bulunan:
                d.yoklama_birimi = agac.get(agac.kisi_birimi(d.personel))
        return render(request, "yoklama/gun_genel.html", _baglam(
            request, **ctx, ozet=servis.ozet(durumlar), gruplar=servis.bolumle(ozetler), q=q, bulunan=bulunan,
            eksik=sum(1 for o in ozetler if o["toplam"] and o["birim"].pk and not o["onay"])))

    from personel.kart import yetki_sirali

    kendi = yetki_sirali(servis.personeller(y, birim, alt=False), birim)  # en yetkili başta, sonra alfabetik
    durumlar = servis.gun_durumu(tarih, kendi)
    filtre = request.GET.get("durum", "")
    secim = {"yok": lambda d: not d.mevcut, "gun_boyu": lambda d: d.gun_boyu, "kismi": lambda d: d.kismi,
             "mevcut": lambda d: d.mevcut}.get(filtre)
    gorunen = [d for d in durumlar if secim(d)] if secim else durumlar
    alt_birimler = [o for o in servis.birim_ozetleri(y, tarih, kok=birim) if o["birim"] != birim and o["toplam"]] \
        if birim.pk else []
    onay = GunlukOnay.objects.filter(birim=birim, tarih=tarih).select_related("onaylayan").first() if birim.pk else None
    return render(request, "yoklama/gun.html", _baglam(
        request, **ctx, durumlar=gorunen, ozet=servis.ozet(durumlar), filtre=filtre, onay=onay,
        alt_birimler=alt_birimler, kendi_sayi=len(kendi),
        gun_kilit=servis.gun_kilidi(y, birim.pk, tarih) if y.giris else None,
        onaylayabilir=bool(kendi) and servis.onay_yetkisi(y, birim), geri_adres=request.get_full_path()))


@require_POST
@login_required
def onay(request):
    y = servis.yetki(request)
    birim = _secili_birim(request, y, varsayilan=False) or y.kapsam_birim
    if birim is None or not birim.pk:
        raise Http404("Birim bulunamadı.")
    tarih = _tarih(request.POST.get("tarih"), timezone.localdate())
    try:
        servis.onayla(request.user, y, birim, tarih)
    except YoklamaHatasi as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{birim.ad}: {tarih:%d.%m.%Y} yoklaması kesinleşti.")
    return _geri(request, f"{reverse('yoklama:ana')}?tarih={tarih.isoformat()}&birim={birim.pk}")


# ---------------------------------------------------------------- personel kartı

@login_required
def kart(request, pk):
    y = _goruntule(request)
    p = servis.kapsamdaki_personel(y, pk)
    bugun = timezone.localdate()
    if request.method == "POST":
        if not y.giris or not y.kapsar(p):
            raise PermissionDenied
        try:
            tur, bas, bit, aciklama = _kayit_formu(request)
            k = servis.ekle(request.user, y, p, tur, bas, bit, aciklama)
        except YoklamaHatasi as e:
            messages.error(request, str(e))
            # hata: kartta kal (girilenler düzeltilsin), dönüş adresi korunur
            hedef = reverse("yoklama:kart", args=[p.pk])
            geri = request.POST.get("geri", "")
            return redirect(f"{hedef}?geri={quote(geri)}" if geri else hedef)
        messages.success(request, f"{p.ad_soyad}: {k.tur.ad} kaydedildi ({k.aralik_metni}).")
        if k.hak_uyarisi:
            messages.warning(request, k.hak_uyarisi)
        # kayıttan sonra geldiği listeye (yoksa personelin birim sayfasına) döner
        return _geri(request, _birim_sayfasi(y, p, k.yerel_bas.date()))
    yil = int(request.GET.get("yil") or bugun.year)
    simdi = timezone.now()
    tum = list(p.yoklama_kayitlari.select_related("tur", "olusturan", "guncelleyen"))
    gelecek = [k for k in tum if k.bitis > simdi]
    gecmis = [k for k in tum if k.bitis <= simdi and k.yerel_bas.year == yil]
    yil_ozeti = servis.yil_ozeti(tum, yil)
    bugun_durum = servis.gun_durumu(bugun, [p])[0]
    girebilir = y.giris and y.kapsar(p)
    ilk_giris = None if y.yonetim else servis.ilk_giris_tarihi()
    kilitli = {k.pk for k in gelecek + gecmis if girebilir and servis.kilit_nedeni(y, p, k.baslangic, k.bitis)}
    varsayilan_tarih = _tarih(request.GET.get("tarih"), bugun)
    if ilk_giris and varsayilan_tarih < ilk_giris:
        varsayilan_tarih = ilk_giris
    yillar = sorted({k.yerel_bas.year for k in tum} | {bugun.year}, reverse=True)
    return render(request, "yoklama/kart.html", _baglam(
        request, p=p, bugun=bugun, bugun_durum=bugun_durum, gelecek=gelecek, gecmis=gecmis, yil=yil, yillar=yillar,
        yil_ozeti=yil_ozeti, hak_onizleme=servis.hak_onizleme(p, [bugun.year - 1, bugun.year, bugun.year + 1]),
        turler=servis.izin_turleri(), girebilir=girebilir, ilk_giris=ilk_giris, kilitli=kilitli,
        foto_yukleyebilir=y.yonetim, geri=_guvenli_geri(request) or _birim_sayfasi(y, p, varsayilan_tarih),
        islemler=list(p.yoklama_gecmisi.select_related("kullanici")[:15]), varsayilan_tarih=varsayilan_tarih))


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
                return _geri(request, kart_url)
            tur, bas, bit, aciklama = _kayit_formu(request)
            yeni = servis.duzenle(request.user, y, k.pk, int(request.POST.get("surum") or 0), tur, bas, bit, aciklama)
        except YoklamaHatasi as e:
            messages.error(request, str(e))
            return redirect(request.path)
        messages.success(request, "Kayıt güncellendi.")
        if yeni.hak_uyarisi:
            messages.warning(request, yeni.hak_uyarisi)
        return _geri(request, kart_url)
    girebilir = y.giris and y.kapsar(p)
    return render(request, "yoklama/kayit.html", _baglam(
        request, k=k, p=p, turler=IzinTuru.objects.filter(aktif=True) | IzinTuru.objects.filter(pk=k.tur_id),
        hak_onizleme=servis.hak_onizleme(p, sorted({k.yerel_bas.year - 1, k.yerel_bas.year, k.yerel_bas.year + 1}),
                                         haric=k.pk),
        girebilir=girebilir, kilit=servis.kilit_nedeni(y, p, k.baslangic, k.bitis) if girebilir else None,
        ilk_giris=None if y.yonetim else servis.ilk_giris_tarihi(), geri=_guvenli_geri(request)))


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
    if not y.yonetim:  # fotoğrafı yalnız yönetim yetkisindekiler (idari işler yetkilisi, sistem yöneticileri) değiştirir
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
        fields = ["ad", "kisa", "grup", "renk", "sira", "aktif", "aciklama", "yillik_hak", "mevcut_sayilir", "rapor_sirasi",
                  "yarim_gun", "hazir_saatler"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # rapor sırası: tür sayısı kadar seçenek (1 = raporda en başta)
        adet = IzinTuru.objects.count() + (0 if self.instance.pk else 1)
        alan = self.fields["rapor_sirasi"]
        self.fields["rapor_sirasi"] = forms.TypedChoiceField(
            label=alan.label, help_text=alan.help_text, required=False, coerce=int, empty_value=None,
            choices=[("", "Sırasız (sonda)")] + [(i, f"{i}.") for i in range(1, max(adet, 1) + 1)])
        self.fields["yillik_hak"].widget.attrs.update({"placeholder": "Boş = sınırsız", "min": 0})
        self.fields["grup"].required = False

    def clean_grup(self):
        return self.cleaned_data.get("grup") or self.instance.grup or "izin"


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
    form.fields["mevcut_sayilir"].widget.attrs["class"] = "form-check-input"
    form.fields["yarim_gun"].widget.attrs["class"] = "form-check-input"
    return render(request, "yoklama/turler.html", _baglam(
        request, turler=IzinTuru.objects.annotate(kullanim=Count("kayitlar")).order_by("sira", "ad"), form=form, duzenlenen=duzenlenen,
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
    birim = _secili_birim(request, y)
    from .rapor import excel

    return excel(bas, bit, list(servis.personeller(y, birim)), birim)


@login_required
def izin_dokumu(request):
    """Yıllık izin dökümü: kişi kişi hangi izni kaç kez, kaç gün kullandı. Ekranda önizleme, ?pdf=1 ile PDF.
    Yalnız tüm okulu yönetenler (idari işler yetkilisi, sistem yöneticileri)."""
    from . import izin_dokumu as dokum

    y = _yonetim(request)
    bugun = timezone.localdate()
    yil = int(request.GET["yil"]) if (request.GET.get("yil") or "").isdigit() else bugun.year
    yil = min(max(yil, 2020), bugun.year + 1)
    birim = _secili_birim(request, y)
    yalniz = request.GET.get("yalniz") == "1"
    veri = dokum.hazirla(y, yil, birim, yalniz)
    if request.GET.get("pdf") == "1":
        return HttpResponse(dokum.pdf(veri), content_type="application/pdf",
                            headers={"Content-Disposition": f'attachment; filename="izin_dokumu_{yil}.pdf"'})
    ilk = YoklamaKaydi.objects.order_by("baslangic").values_list("baslangic", flat=True).first()
    ilk_yil = timezone.localtime(ilk).year if ilk else bugun.year
    return render(request, "yoklama/izin_dokumu.html", _baglam(
        request, v=veri, yil=yil, yillar=range(bugun.year + 1, min(ilk_yil, bugun.year) - 1, -1), yalniz=yalniz,
        secili_birim=birim, birim_q=_birim_q(birim), birim_secenekleri=servis.birim_secenekleri(y)))


@login_required
def gecmis(request):
    y = _goruntule(request)
    qs = YoklamaGecmisi.objects.select_related("personel__bolum", "kullanici")
    if not y.tum_okul:
        qs = qs.filter(personel__in=servis.personeller(y))
    if request.GET.get("onay_sonrasi") == "1":
        qs = qs.filter(onay_sonrasi=True)
    return render(request, "yoklama/gecmis.html", _baglam(request, islemler=list(qs[:300]),
                                                          onay_sonrasi=request.GET.get("onay_sonrasi") == "1"))


# ---------------------------------------------------------------- günlük yoklama formu (resmî biçim)

@login_required
def yoklama_formu(request):
    """Kurumun günlük yoklama formu: ekranda yazdırılabilir, ?excel=1 ile Excel (aralıkta her gün ayrı sayfa)."""
    from . import form as yform

    y = _goruntule(request)
    bugun = timezone.localdate()
    tarih = _tarih(request.GET.get("tarih"), bugun)
    birim = _secili_birim(request, y)
    kisiler = list(servis.personeller(y, birim))
    if request.GET.get("excel") == "1":
        bit = _tarih(request.GET.get("bit"), tarih)
        return yform.excel(yform.gun_listesi(tarih, bit), kisiler, birim)
    f = yform.gunluk(tarih, kisiler, birim)
    return render(request, "yoklama/form.html", _baglam(
        request, tarih=tarih, secili_birim=birim, birim_q=_birim_q(birim), f=f,
        birim_secenekleri=servis.birim_secenekleri(y),
        bos_satirlar=range(len(f["beyan"]) + 1, max(yform.EN_AZ_BEYAN_SATIRI, len(f["beyan"])) + 1), dun=tarih - datetime.timedelta(days=1),
        yarin=tarih + datetime.timedelta(days=1), sutunlar=yform.SUTUNLAR))


@login_required
def gruplar(request):
    """İdari işler yetkilisi: personelin yoklama formundaki sütunu ve "Görevi" metni (boş = otomatik)."""
    from . import form as yform

    y = _yonetim(request)
    kisiler = list(servis.personeller(y))
    ata = yform.atamalar(kisiler)
    gecerli = {g for g, _ in PersonelGrubu.GRUPLAR}
    if request.method == "POST":
        degisen = 0
        for p in kisiler:
            if f"grup-{p.pk}" not in request.POST:  # sayfa açıldıktan sonra eklenen personel: dokunma
                continue
            grup = request.POST.get(f"grup-{p.pk}", "")
            gorev = request.POST.get(f"gorev-{p.pk}", "").strip()[:80]
            if grup not in gecerli:
                grup = ""
            if grup == yform.otomatik_grup(p):
                grup = ""  # otomatikle aynıysa atama tutma; künye değişince kendiliğinden güncellensin
            eski = ata.get(p.pk)
            if (eski.grup if eski else "", eski.gorev if eski else "") == (grup, gorev):
                continue
            if grup or gorev:
                PersonelGrubu.objects.update_or_create(personel=p, defaults={"grup": grup, "gorev": gorev})
            elif eski:
                eski.delete()
            degisen += 1
        messages.success(request, f"{degisen} personelin yoklama grubu güncellendi." if degisen else "Değişiklik yok.")
        return redirect(request.get_full_path())
    satirlar, sayilar = [], dict.fromkeys(yform.SUTUNLAR, 0)
    for p in kisiler:
        a = ata.get(p.pk)
        oto = yform.otomatik_grup(p)
        grup, gorev = yform.grup_ve_gorev(p, a)
        sayilar[grup] += 1
        satirlar.append({"p": p, "oto": oto, "oto_ad": yform.GRUP_ADI[oto], "grup": grup, "elle": bool(a and a.grup),
                         "gorev": a.gorev if a else "", "oto_gorev": yform.otomatik_gorev(p, grup)})
    return render(request, "yoklama/gruplar.html", _baglam(
        request, satirlar=satirlar, gruplar=PersonelGrubu.GRUPLAR,
        sayilar=[(g, ad, sayilar[g]) for g, ad in PersonelGrubu.GRUPLAR]))
