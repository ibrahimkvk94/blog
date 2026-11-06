"""Salon durumu sayfaları: yıl (iPhone yıl görünümü gibi), ay, gün (saat çizelgesi) ve kayıt girişi.

Görüntüleme herkese açıktır (giriş yapmış her kullanıcı); kayıt girme, düzenleme ve silme Salon Durumu biriminde
Düzenleme yetkisi ister.
"""

import datetime
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from . import servis
from .models import GUN_BAS, GUN_BIT, SalonKaydi
from .servis import SalonHatasi


def _tarih(metin, varsayilan=None):
    try:
        return datetime.date.fromisoformat(metin or "")
    except ValueError:
        return varsayilan


def _saat(metin):
    try:
        return datetime.time.fromisoformat(metin or "")
    except ValueError:
        return None


def _secili(request):
    """Gösterilen salonlar (?s=1,3); verilmezse kullanımdaki hepsi."""
    hepsi = servis.salonlar()
    istenen = {int(x) for x in (request.GET.get("s") or "").split(",") if x.isdigit()}
    secili = [s for s in hepsi if s.pk in istenen] or hepsi
    return hepsi, secili


def _baglam(request, **ctx):
    hepsi, secili = ctx.get("hepsi"), ctx.get("secili")
    s_q = "" if hepsi is None or len(secili) == len(hepsi) else ",".join(str(s.pk) for s in secili)
    ctx.setdefault("duzenleyebilir", servis.duzenleyebilir(request))
    ctx["s_q"] = s_q
    ctx["sq"] = f"&s={s_q}" if s_q else ""
    if hepsi is not None:
        # filtre bağlantıları: bir salonu aç / kapa
        ids = {s.pk for s in secili}
        ctx["filtre"] = [{"salon": s, "secili": s.pk in ids,
                          "q": ",".join(str(x.pk) for x in hepsi if (x.pk in ids) != (x.pk == s.pk))} for s in hepsi]
    try:
        from core.yetki import birim_bul, yol

        request.birim = birim_bul(request, servis.BIRIM)
        ctx.setdefault("yol", yol(request, request.birim))
    except Exception:
        pass
    return ctx


def yil(request):
    bugun = timezone.localdate()
    try:
        yil_no = int(request.GET.get("yil") or bugun.year)
    except ValueError:
        yil_no = bugun.year
    yil_no = min(max(yil_no, 2000), 2100)
    hepsi, secili = _secili(request)
    return render(request, "salon/yil.html", _baglam(
        request, hepsi=hepsi, secili=secili, yil=yil_no, bugun=bugun, aylar=servis.yil(yil_no, secili, bugun),
        durum=servis.simdiki_durum(secili, timezone.localtime()), gun_adlari=["Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz"]))


def ay(request, yil_no, ay_no):
    if not 1 <= ay_no <= 12 or not 2000 <= yil_no <= 2100:
        return redirect("salon:yil")
    bugun = timezone.localdate()
    hepsi, secili = _secili(request)
    ilk = datetime.date(yil_no, ay_no, 1)
    onceki = (ilk - datetime.timedelta(days=1)).replace(day=1)
    sonraki = (ilk + datetime.timedelta(days=32)).replace(day=1)
    return render(request, "salon/ay.html", _baglam(
        request, hepsi=hepsi, secili=secili, yil=yil_no, ay=ay_no, ay_adi=servis.AYLAR[ay_no - 1], bugun=bugun,
        haftalar=servis.ay(yil_no, ay_no, secili, bugun), onceki=onceki, sonraki=sonraki, breadcrumb_ek=True,
        gun_adlari=servis.GUNLER))


def gun(request, tarih):
    t = _tarih(tarih)
    if t is None:
        return redirect("salon:yil")
    hepsi, secili = _secili(request)
    simdi = timezone.localtime()
    sutunlar, saatler = servis.gun(t, secili, simdi)
    hafta_bas = t - datetime.timedelta(days=t.weekday())
    simdi_ust = None
    if simdi.date() == t:
        dk = simdi.hour * 60 + simdi.minute
        bas, bit = GUN_BAS.hour * 60, GUN_BIT.hour * 60
        if bas <= dk <= bit:
            simdi_ust = round((dk - bas) * 100 / (bit - bas), 3)
    return render(request, "salon/gun.html", _baglam(
        request, hepsi=hepsi, secili=secili, t=t, gun_adi=servis.GUNLER[t.weekday()], ay_adi=servis.AYLAR[t.month - 1],
        sutunlar=sutunlar, saatler=saatler, simdi_ust=simdi_ust, breadcrumb_ek=True,
        hafta=[{"tarih": hafta_bas + datetime.timedelta(days=i), "ad": ["Pt", "Sa", "Ça", "Pe", "Cu", "Ct", "Pz"][i]}
               for i in range(7)],
        onceki=t - datetime.timedelta(days=1), sonraki=t + datetime.timedelta(days=1), bugun=simdi.date(),
        gun_bas=GUN_BAS, gun_bit=GUN_BIT))


def _geri(request, varsayilan):
    hedef = request.POST.get("geri") or request.GET.get("geri") or ""
    if hedef and url_has_allowed_host_and_scheme(hedef, allowed_hosts={request.get_host()}):
        return hedef
    return varsayilan


def _formdan(request):
    tum_gun = request.POST.get("tum_gun") == "1"
    return {"tarih": _tarih(request.POST.get("tarih")), "tum_gun": tum_gun,
            "bas": None if tum_gun else _saat(request.POST.get("bas")),
            "bit": None if tum_gun else _saat(request.POST.get("bit")),
            "baslik": request.POST.get("baslik", ""), "aciklama": request.POST.get("aciklama", "")}


def yeni(request):
    if not servis.duzenleyebilir(request):
        raise PermissionDenied("Salon kaydı girmek için Salon Durumu biriminde Düzenleme yetkisi gerekir.")
    hepsi = servis.salonlar()
    v = {"tarih": _tarih(request.GET.get("tarih"), timezone.localdate()), "tum_gun": False,
         "bas": _saat(request.GET.get("bas")) or datetime.time(9, 0), "bit": None, "baslik": "", "aciklama": ""}
    if v["bit"] is None:
        b = v["bas"]
        v["bit"] = datetime.time(min(b.hour + 1, 23), b.minute)
    secilen = {int(x) for x in request.GET.getlist("salon") if x.isdigit()}
    tekrar, tekrar_bitis = False, None
    if request.method == "POST":
        v = _formdan(request)
        secilen = {int(x) for x in request.POST.getlist("salon") if x.isdigit()}
        tekrar = request.POST.get("tekrar") == "hafta"
        tekrar_bitis = _tarih(request.POST.get("tekrar_bitis")) if tekrar else None
        try:
            if v["tarih"] is None:
                raise SalonHatasi("Tarih seçin.")
            if tekrar and tekrar_bitis is None:
                raise SalonHatasi("Haftalık tekrar için bitiş tarihini seçin.")
            kayitlar = servis.ekle(request.user, [s for s in hepsi if s.pk in secilen], v["tarih"], v["tum_gun"],
                                   v["bas"], v["bit"], v["baslik"], v["aciklama"], tekrar_bitis)
        except SalonHatasi as e:
            messages.error(request, str(e))
        else:
            k = kayitlar[0]
            messages.success(request, f"{len(kayitlar)} kayıt girildi: {k.baslik} · {k.saat_metni}"
                                      + (f" · {len({x.tarih for x in kayitlar})} hafta" if tekrar else ""))
            return redirect(_geri(request, reverse("salon:gun", args=[k.tarih.isoformat()])))
    return render(request, "salon/kayit.html", _baglam(
        request, hepsi=None, salonlar=hepsi, secilen=secilen or {hepsi[0].pk} if hepsi else set(), v=v,
        tekrar=tekrar, tekrar_bitis=tekrar_bitis, k=None, breadcrumb_ek=True, geri=_geri(request, "")))


def kayit(request, pk):
    k = get_object_or_404(SalonKaydi.objects.select_related("salon", "olusturan", "guncelleyen"), pk=pk)
    duzenleyebilir = servis.duzenleyebilir(request)
    hepsi = servis.salonlar(sadece_aktif=False)
    gun_url = reverse("salon:gun", args=[k.tarih.isoformat()])
    v = {"tarih": k.tarih, "tum_gun": k.tum_gun, "bas": k.bas, "bit": k.bit, "baslik": k.baslik, "aciklama": k.aciklama}
    if request.method == "POST":
        if not duzenleyebilir:
            raise PermissionDenied("Salon kaydını değiştirmek için Salon Durumu biriminde Düzenleme yetkisi gerekir.")
        islem = request.POST.get("islem")
        if islem in ("sil", "seri_sil"):
            if islem == "seri_sil" and k.seri:
                silinen = SalonKaydi.objects.filter(seri=k.seri, tarih__gte=k.tarih).delete()[0]
                messages.success(request, f"Seri silindi: bu ve sonraki {silinen} kayıt.")
            else:
                k.delete()
                messages.success(request, "Kayıt silindi.")
            return redirect(_geri(request, gun_url))
        v = _formdan(request)
        salon = next((s for s in hepsi if str(s.pk) == request.POST.get("salon")), None)
        try:
            if v["tarih"] is None or salon is None:
                raise SalonHatasi("Salon ve tarih seçin.")
            servis.duzenle(request.user, k, salon, v["tarih"], v["tum_gun"], v["bas"], v["bit"], v["baslik"], v["aciklama"])
        except SalonHatasi as e:
            messages.error(request, str(e))
        else:
            messages.success(request, "Kayıt güncellendi.")
            return redirect(_geri(request, reverse("salon:gun", args=[k.tarih.isoformat()])))
    seri_sayisi = SalonKaydi.objects.filter(seri=k.seri, tarih__gte=k.tarih).count() if k.seri else 0
    return render(request, "salon/kayit.html", _baglam(
        request, hepsi=None, salonlar=hepsi, secilen={k.salon_id}, v=v, k=k, seri_sayisi=seri_sayisi,
        duzenleyebilir=duzenleyebilir, breadcrumb_ek=True, geri=_geri(request, "")))

