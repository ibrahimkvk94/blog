"""Öğrenci Kaydı: öğrenci kütüğü (kimlik ve kayıt bilgileri).

Yetki ("Öğrenci Kaydı" birimi): görüntüleme listeyi görür (T.C. no ve aile bilgileri gizli); yönetim T.C. no ve tüm
kimlik bilgilerini görür, öğrenci ekler / düzenler. Kimlik kartından toplu kayıt: Kimlik Kartı Okuma.
"""

import datetime
from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.iki_adim import karekod_svg
from core.arama import ara
from core.yetki import GORUNTULEME, YONETIM, yetki_gerekli, yol
from kimlik.okuma import tr_buyuk
from personel.models import Bolum

from .models import Ogrenci

BIRIM = "ogrenci-kaydi"
OKUYUCU = Path(__file__).resolve().parent / "okuyucu" / "Ogrenci_KareKod_Okuyucu.xlsm"


class OgrenciFormu(forms.ModelForm):
    class Meta:
        model = Ogrenci
        fields = ["tc", "soyad", "ad", "numara", "sinif", "bolum", "dogum_tarihi", "cinsiyet", "seri_no", "uyruk",
                  "son_gecerlilik", "anne_adi", "baba_adi", "veren_makam", "aktif"]
        widgets = {
            "dogum_tarihi": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "son_gecerlilik": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bolum"].queryset = Bolum.objects.filter(aktif=True)
        self.fields["soyad"].required = self.fields["ad"].required = True
        for ad, f in self.fields.items():
            if ad != "aktif":
                f.widget.attrs["class"] = "form-select" if isinstance(f.widget, forms.Select) else "form-control"
        self.fields["aktif"].widget.attrs["class"] = "form-check-input"

    def clean_tc(self):
        from kimlik.okuma import tc_gecerli

        tc = "".join(c for c in self.cleaned_data.get("tc", "") if c.isdigit())
        if tc and not tc_gecerli(tc):
            raise forms.ValidationError("T.C. kimlik no geçersiz.")
        if tc and Ogrenci.objects.filter(tc=tc).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Bu T.C. kimlik no ile kayıtlı başka öğrenci var.")
        return tc

    def clean(self):
        veri = super().clean()
        for ad in ("soyad", "ad", "anne_adi", "baba_adi", "veren_makam", "seri_no"):
            if veri.get(ad):
                veri[ad] = " ".join(tr_buyuk(veri[ad]).split())
        return veri


def _yonetici(request):
    return request.yetki_seviye >= YONETIM


def _liste(request):
    q = request.GET.get("q", "").strip()
    durum = request.GET.get("durum", "aktif")
    qs = Ogrenci.objects.select_related("bolum")
    if durum == "aktif":
        qs = qs.filter(aktif=True)
    elif durum == "pasif":
        qs = qs.filter(aktif=False)
    if request.GET.get("bolum", "").isdigit():
        qs = qs.filter(bolum_id=request.GET["bolum"])
    if q:
        alanlar = ["ad", "soyad", "numara", "sinif"] + (["tc"] if _yonetici(request) else [])
        qs = ara(qs, q, *alanlar)
    return qs, q, durum


@yetki_gerekli(BIRIM, GORUNTULEME)
def liste(request):
    qs, q, durum = _liste(request)
    return render(request, "ogrenci/liste.html", {
        "yol": yol(request, request.birim), "ogrenciler": qs[:1000], "toplam": qs.count(), "q": q, "durum": durum,
        "bolumler": Bolum.objects.filter(aktif=True), "secili_bolum": request.GET.get("bolum", ""),
        "yonetici": _yonetici(request), "sekme": "liste"})


@yetki_gerekli(BIRIM, GORUNTULEME)
def excel(request):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    qs, _, _ = _liste(request)
    yonetici = _yonetici(request)
    wb = Workbook()
    ws = wb.active
    ws.title = "Öğrenciler"
    basliklar = ["Öğrenci no", "Soyadı", "Adı", "Sınıf / şube", "Bölüm"]
    if yonetici:
        basliklar += ["T.C. Kimlik No", "Doğum Tarihi", "Cinsiyeti", "Seri No", "Uyruğu", "Son Geçerlilik",
                      "Anne Adı", "Baba Adı", "Veren Makam"]
    ws.append(basliklar)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
    for o in qs:
        satir = [o.numara, o.soyad, o.ad, o.sinif, o.bolum.ad if o.bolum_id else ""]
        if yonetici:
            satir += [o.tc, o.dogum_tarihi, o.get_cinsiyet_display(), o.seri_no, o.uyruk, o.son_gecerlilik,
                      o.anne_adi, o.baba_adi, o.veren_makam]
        ws.append(satir)
    for i in range(1, len(basliklar) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 16
        for hucre in ws.iter_cols(min_col=i, max_col=i, min_row=2):
            for c in hucre:
                if isinstance(c.value, datetime.date):
                    c.number_format = "DD.MM.YYYY"
    ws.freeze_panes = "D2"
    cevap = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    cevap["Content-Disposition"] = 'attachment; filename="ogrenciler.xlsx"'
    wb.save(cevap)
    return cevap


@yetki_gerekli(BIRIM, YONETIM)
def duzenle(request, pk=None):
    o = get_object_or_404(Ogrenci, pk=pk) if pk else None
    form = OgrenciFormu(request.POST or None, instance=o)
    if request.method == "POST" and form.is_valid():
        o = form.save()
        messages.success(request, f"{o.ad_soyad} kaydedildi.")
        return redirect("ogrenci:liste")
    return render(request, "ogrenci/form.html", {"yol": yol(request, request.birim), "form": form, "nesne": o,
                                                 "breadcrumb_ek": True})


# --- Kare kodlu öğrenci bilgi formu ------------------------------------------------------------------------------
# Öğrenci formu kendi telefonunda doldurur; bilgiler sunucuya gönderilmez, kare kod tarayıcıda üretilir.
# Kayıt masasında kod USB kare kod okuyucuyla "Öğrenci Kare Kod Okuyucu" Excel'ine (ağa bağlı olmayan PC) okutulur.

@login_not_required
def bilgi_formu(request):
    """Herkese açık form sayfası (giriş gerekmez). Sunucuya veri gelmez: sayfada form gönderimi yoktur."""
    return render(request, "ogrenci/bilgi_formu.html")


def form_adresi(request):
    """Öğrencilerin açacağı adres: internet (Funnel) adresi varsa o, yoksa sayfanın açıldığı adres."""
    yol_ = reverse("ogrenci:bilgi_formu")
    if settings.DIS_ADRESLER:
        return settings.DIS_ADRESLER[0] + yol_
    return request.build_absolute_uri(yol_)


@yetki_gerekli(BIRIM, GORUNTULEME)
def karekod(request):
    adres = form_adresi(request)
    return render(request, "ogrenci/karekod.html", {
        "yol": yol(request, request.birim), "adres": adres, "karekod": karekod_svg(adres),
        "dis_adres_var": bool(settings.DIS_ADRESLER), "okuyucu_var": OKUYUCU.exists(), "sekme": "karekod"})


@yetki_gerekli(BIRIM, GORUNTULEME)
def okuyucu_indir(request):
    if not OKUYUCU.exists():
        raise Http404("Okuyucu Excel dosyası sunucuda yok.")
    return FileResponse(OKUYUCU.open("rb"), as_attachment=True, filename=OKUYUCU.name,
                        content_type="application/vnd.ms-excel.sheet.macroEnabled.12")
