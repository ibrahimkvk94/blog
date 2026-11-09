"""Vekâlet sayfaları (İdari İşler · Vekâlet).
- Vekâletler: kimin kime, hangi görev için, ne zamana kadar vekâlet ettiği (görüntüleme yetkisi olan herkes).
- Vekâlet işlemleri: kayıt ekleme / düzenleme / erken sonlandırma (yalnız düzenleme yetkisi olanlar, İdari İşler)."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.yetki import birim_bul, yol

from . import servis
from .models import Vekalet


class PersonelSecimi(forms.ModelChoiceField):
    def label_from_instance(self, p):
        return f"{p.ad_soyad} · {p.kunye}" if p.kunye else p.ad_soyad


class VekaletFormu(forms.ModelForm):
    veren = PersonelSecimi(queryset=servis.personel_listesi(), label="Vekâlet veren (asıl)",
                           empty_label="Personel seçin…")
    vekil = PersonelSecimi(queryset=servis.personel_listesi(), label="Vekil", empty_label="Personel seçin…")

    class Meta:
        model = Vekalet
        fields = ["veren", "gorev", "vekil", "neden", "baslangic", "bitis", "aciklama"]
        widgets = {
            "baslangic": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "bitis": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "aciklama": forms.TextInput(attrs={"placeholder": "ör. rapor no, onay yazısı tarihi / sayısı"}),
            "gorev": forms.TextInput(attrs={"placeholder": "ör. Bilgisayar Teknolojisi Bölüm Başkanı",
                                            "list": "vkGorevler"}),
        }

    def __init__(self, *args, veren_idler=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["veren"].queryset = servis.personel_listesi()
        if veren_idler is not None:  # kendi birimi kapsamlı hesap: yalnız biriminin personeli vekâlet verir
            self.fields["veren"].queryset = servis.personel_listesi().filter(pk__in=veren_idler)
        self.fields["vekil"].queryset = servis.personel_listesi()
        for ad, alan in self.fields.items():
            alan.widget.attrs.setdefault("class", "form-select" if ad in ("veren", "vekil", "neden") else "form-control")


def _baglam(request, y, sekme, **ek):
    request.birim = birim_bul(request, servis.BIRIM)
    return {"yol": yol(request, request.birim), "y": y, "sekme": sekme, **ek}


@login_required
def liste(request):
    y = servis.yetki(request)
    if not y.goruntule:
        raise PermissionDenied
    tumu = request.GET.get("tumu") == "1"
    yururlukte, baslayacak, gecmis = servis.gruplar(tumu=tumu)
    return render(request, "vekalet/liste.html", _baglam(
        request, y, "liste", yururlukte=yururlukte, baslayacak=baslayacak, gecmis=gecmis, tumu=tumu,
        bugun=timezone.localdate()))


@login_required
def islemler(request, pk=None):
    y = servis.yetki(request)
    if not y.duzenle:
        raise PermissionDenied
    nesne = get_object_or_404(Vekalet, pk=pk) if pk else None
    if nesne is not None and not y.kapsar(nesne):
        raise PermissionDenied
    uyarilar = []
    gorevler = servis.gorev_onerileri(y)
    if request.method == "POST":
        form = VekaletFormu(request.POST, instance=nesne, veren_idler=y.veren_idler)
        if form.is_valid():
            v = form.save(commit=False)
            hatalar, uyarilar = servis.kontrol(v)
            for h in hatalar:
                form.add_error(None, h)
            if not hatalar and (not uyarilar or request.POST.get("onay") == "1"):
                if v.pk is None:
                    v.olusturan = request.user
                v.guncelleyen = request.user
                v.save()
                messages.success(request, f"Vekâlet kaydedildi: {v.veren.ad_soyad} → {v.vekil.ad_soyad} "
                                          f"({v.gorev}, {v.aralik_metni}).")
                return redirect("vekalet:islemler")
    else:
        ilk = None
        if nesne is None:  # "vekâleti girilmemiş yönetici" kutusundan: ?veren=&bas=&bit=&neden=
            g = request.GET
            ilk = {"baslangic": g.get("bas") or timezone.localdate(), "bitis": g.get("bit") or None,
                   "neden": g.get("neden") if g.get("neden") in dict(Vekalet.NEDENLER) else Vekalet.RAPOR}
            veren = int(g["veren"]) if g.get("veren", "").isdigit() else y.varsayilan_veren
            if veren:
                ilk["veren"] = veren
                ilk["gorev"] = gorevler.get(veren, "")
        form = VekaletFormu(instance=nesne, initial=ilk, veren_idler=y.veren_idler)
    durum = request.GET.get("durum", "")
    kayitlar = Vekalet.objects.select_related("veren", "vekil", "olusturan")
    if y.veren_idler is not None:
        kayitlar = kayitlar.filter(veren_id__in=y.veren_idler)
    kayitlar = list(kayitlar[:300])
    sayilar = {k: 0 for k in Vekalet.DURUM_ADI}
    for v in kayitlar:
        sayilar[v.durum] += 1
    if durum in Vekalet.DURUM_ADI:
        kayitlar = [v for v in kayitlar if v.durum == durum]
    return render(request, "vekalet/islemler.html", _baglam(
        request, y, "islemler", form=form, nesne=nesne, uyarilar=uyarilar, kayitlar=kayitlar, durum=durum,
        sayilar=sayilar, toplam=sum(sayilar.values()), durumlar=Vekalet.DURUM_ADI, gorevler=gorevler,
        izinler=servis.yaklasan_izinler(), gorev_listesi=servis.gorev_listesi(),
        eksikler=servis.eksik_vekaletler(y=y) if nesne is None else []))


@require_POST
@login_required
def sonlandir(request, pk):
    y = servis.yetki(request)
    if not y.duzenle:
        raise PermissionDenied
    v = get_object_or_404(Vekalet, pk=pk)
    if not y.kapsar(v):
        raise PermissionDenied
    if v.sonlandirma:
        v.sonlandirma, v.sonlandiran = None, None
        messages.info(request, f"Erken sonlandırma geri alındı: {v}.")
    else:
        v.sonlandirma, v.sonlandiran = timezone.now(), request.user
        messages.success(request, f"Vekâlet erken sonlandırıldı: {v}.")
    v.guncelleyen = request.user
    v.save()
    return redirect("vekalet:islemler")


@require_POST
@login_required
def sil(request, pk):
    y = servis.yetki(request)
    if not y.duzenle:
        raise PermissionDenied
    v = get_object_or_404(Vekalet, pk=pk)
    if not y.kapsar(v):
        raise PermissionDenied
    messages.success(request, f"Vekâlet kaydı silindi: {v}.")
    v.delete()
    return redirect("vekalet:islemler")
