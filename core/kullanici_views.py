"""Kullanıcılar ve yetkiler sayfaları (yalnız sistem yöneticileri). Mantık: core/kullanicilar.py."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts import guvenilir
from accounts.guvenlik import basarili_giris
from accounts.models import IkiAdimliDogrulama

from . import kullanicilar as ky
from .bolum_yetkileri import moduller
from .kullanici_formlari import HesapFormu, ParolaFormu, YeniHesapFormu
from .models import Yetki


def _yonetici(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _baglam(sekme, **ek):
    return {"sekme": sekme, "breadcrumb_ek": True, "seviye_adlari": ky.SEVIYE_ADLARI, **ek}


@login_required
def kullanicilar(request):
    _yonetici(request)
    if request.method == "POST":
        n = ky.tablo_kaydet(request.user, request.POST.getlist("c"))
        messages.success(request, f"Yetkiler kaydedildi ({n} değişiklik)." if n else "Değişiklik yok.")
        hedef = reverse("core:kullanicilar")
        tur = request.POST.get("tur", "")
        return redirect(f"{hedef}?tur={tur}" if tur.isalpha() else hedef)
    mods, satirlar = ky.tablo()
    return render(request, "core/kullanicilar.html", _baglam(
        "liste", moduller=mods, gruplar=ky.modul_gruplari(mods), satirlar=satirlar, ozet=ky.ozet(satirlar),
        secili_tur=request.GET.get("tur", ""), gecmis=ky.gecmis(adet=6)))


def _yetki_istegi(post, mods):
    istek = {}
    for m in mods:
        s = post.get(f"s_{m.id}", "")
        if s.isdigit():
            k = post.get(f"k_{m.id}") or Yetki.BOLUM
            istek[m.id] = (int(s), k if k in ky.KAPSAM_ADLARI else Yetki.BOLUM)
    return istek


def _degisen_alanlar(form):
    adlar = {"first_name": "ad", "last_name": "soyad", "bolum": "bölüm", "teskilat_birimi": "teşkilat birimi",
             "personel": "bağlı personel", "is_active": "hesap durumu", "parola_degismeli": "parola değiştirme"}
    parcalar = []
    for alan in form.changed_data:
        deger = form.cleaned_data.get(alan)
        if isinstance(deger, bool):
            deger = "açık" if deger else "kapalı"
        parcalar.append(f"{adlar.get(alan, alan)}: {deger if deger not in (None, '') else '—'}")
    return "; ".join(parcalar)


@login_required
def kullanici(request, pk):
    _yonetici(request)
    User = get_user_model()
    u = get_object_or_404(User, pk=pk)
    kendisi = u.pk == request.user.pk
    salt_okunur = u.is_superuser  # sistem yöneticisi hesapları Yönetim Paneli'nden değişir
    mods = moduller()
    bilgi_formu = HesapFormu(instance=u, prefix="h")
    parola_formu = ParolaFormu(kullanici=u, prefix="p")
    if request.method == "POST":
        if salt_okunur:
            raise PermissionDenied
        islem = request.POST.get("islem")
        if islem == "bilgi":
            bilgi_formu = HesapFormu(request.POST, instance=u, prefix="h")
            if bilgi_formu.is_valid():
                if bilgi_formu.changed_data:
                    bilgi_formu.save()
                    ky.gunluge_yaz(request.user, u, "Hesap: " + _degisen_alanlar(bilgi_formu))
                    if "is_active" in bilgi_formu.changed_data and not u.is_active:
                        ky.oturumlari_kapat(u)
                    messages.success(request, "Hesap bilgileri kaydedildi.")
                else:
                    messages.info(request, "Değişiklik yok.")
                return redirect("core:kullanici", pk=u.pk)
        elif islem == "yetki":
            kaldir = [int(x) for x in request.POST.getlist("kaldir") if x.isdigit()]
            n = ky.hesap_yetkileri_kaydet(request.user, u, _yetki_istegi(request.POST, mods), kaldir)
            messages.success(request, f"Yetkiler kaydedildi ({n} değişiklik)." if n else "Değişiklik yok.")
            return redirect("core:kullanici", pk=u.pk)
        elif islem == "parola":
            parola_formu = ParolaFormu(request.POST, kullanici=u, prefix="p")
            if parola_formu.is_valid():
                u.set_password(parola_formu.cleaned_data["parola"])
                u.parola_degismeli = parola_formu.cleaned_data["degistirsin"]
                u.save(update_fields=["password", "parola_degismeli"])
                cihaz = guvenilir.kaldir(u)
                oturum = ky.oturumlari_kapat(u)
                basarili_giris(u.username)
                ky.gunluge_yaz(request.user, u, "Parola yenilendi" + (
                    " (ilk girişte değiştirecek)" if u.parola_degismeli else "") +
                    f"; {cihaz} güvenilir cihaz ve {oturum} açık oturum kapatıldı")
                messages.success(request, f"{u.username} hesabının parolası yenilendi. Açık oturumları ve güvenilir "
                                          f"cihazları kapatıldı.")
                return redirect("core:kullanici", pk=u.pk)
        elif islem in ("iki_adim", "cihazlar", "oturumlar", "kilit"):
            if islem == "iki_adim":
                IkiAdimliDogrulama.objects.filter(kullanici=u).delete()
                metin = "İki adımlı doğrulama sıfırlandı (kullanıcı yeniden kurar)"
            elif islem == "cihazlar":
                metin = f"Güvenilir cihazlar kaldırıldı ({guvenilir.kaldir(u)})"
            elif islem == "oturumlar":
                metin = f"Açık oturumlar kapatıldı ({ky.oturumlari_kapat(u)})"
            else:
                basarili_giris(u.username)
                metin = "Giriş kilidi açıldı"
            ky.gunluge_yaz(request.user, u, metin)
            messages.success(request, metin + ".")
            return redirect("core:kullanici", pk=u.pk)
    ky.isle(u)
    dogrudan = {y.birim_id: y for y in Yetki.objects.filter(kullanici=u).select_related("birim")}
    satirlar = [{"modul": m, **ky.hucre(u, m, dogrudan)} for m in mods]
    # "şu hesaptan kopyala" için diğer hesapların modül yetkileri (etkin seviye)
    hesaplar = list(User.objects.filter(is_superuser=False, is_active=True).exclude(pk=u.pk)
                    .prefetch_related("yetkiler").select_related("bolum", "teskilat_birimi").order_by("username"))
    kopya = {}
    for h in hesaplar:
        hd = {y.birim_id: y for y in h.yetkiler.all()}
        kopya[h.pk] = {m.id: [c["seviye"], c["kapsam"]] for m in mods if (c := ky.hucre(h, m, hd))["seviye"]}
    return render(request, "core/kullanici.html", _baglam(
        "liste", h=u, kendisi=kendisi, salt_okunur=salt_okunur, satirlar=satirlar, gruplar=ky.modul_gruplari(mods),
        diger=ky.diger_yetkiler(u), bilgi_formu=bilgi_formu, parola_formu=parola_formu,
        varsayilan_kapsam=ky.varsayilan_kapsam(u), gecmis=ky.gecmis(u, 25),
        cihazlar=list(u.guvenilir_cihazlar.all()), iki_adim=IkiAdimliDogrulama.objects.filter(kullanici=u).first(),
        kopya_hesaplar=[(h, ky.gorunen_ad(h)) for h in hesaplar if kopya[h.pk]], kopya_json=kopya,
        onerilen_parola=ky.parola_uret()))


@login_required
def kullanici_yeni(request):
    _yonetici(request)
    form = YeniHesapFormu(request.POST or None, initial={"parola": ky.parola_uret(), "parola_degismeli": True})
    if request.method == "POST" and form.is_valid():
        u = form.save(commit=False)
        u.set_password(form.cleaned_data["parola"])
        u.save()
        kaynak = form.cleaned_data.get("sablon")
        n = ky.yetkileri_kopyala(kaynak, u) if kaynak else 0
        ky.gunluge_yaz(request.user, u, "Hesap açıldı" + (f"; {n} yetki {kaynak.username} hesabından kopyalandı"
                                                          if kaynak else ""), ekleme=True)
        messages.success(request, f"{u.username} hesabı açıldı." + (f" {n} yetki kopyalandı." if n else
                                                                    " Yetkilerini aşağıdan verin."))
        return redirect("core:kullanici", pk=u.pk)
    return render(request, "core/kullanici_yeni.html", _baglam("yeni", form=form, zayif=getattr(form, "zayif", False)))


@login_required
def kullanici_gecmisi(request):
    _yonetici(request)
    return render(request, "core/kullanici_gecmisi.html", _baglam("gecmis", gecmis=ky.gecmis(adet=300)))
