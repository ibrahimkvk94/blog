from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from accounts.guvenlik import dis_erisim_mi

from . import servis
from .models import Is, IsNotu

SEKMELER = [("acik", "Açık işler"), ("tamam", "Tamamlananlar"), ("hepsi", "Tümü")]


def liste(request):
    servis.sahip_gerekli(request)
    if request.method == "POST":
        return _islem(request)
    sekme = request.GET.get("sekme", "acik")
    if sekme not in dict(SEKMELER):
        sekme = "acik"
    qs = Is.objects.prefetch_related("notlar__yazan").select_related("olusturan")
    if sekme == "acik":
        qs = qs.filter(durum__in=Is.ACIK)
    elif sekme == "tamam":
        qs = qs.filter(durum__in=(Is.TAMAM, Is.IPTAL))
    sira = {Is.SORU: 0, Is.ONAY: 1, Is.YAPILIYOR: 2, Is.BEKLIYOR: 3, Is.TAMAM: 4, Is.IPTAL: 5}
    onc = {Is.ACIL: 0, Is.NORMAL: 1, Is.DUSUK: 2}
    isler = sorted(qs, key=lambda i: (sira.get(i.durum, 9), onc.get(i.oncelik, 1), -i.olusturma.timestamp()))
    sayilar = {d: Is.objects.filter(durum=d).count() for d, _ in Is.DURUMLAR}
    return render(request, "isler/liste.html", {
        "isler": isler, "sekme": sekme, "sekmeler": SEKMELER, "sayilar": sayilar, "oncelikler": Is.ONCELIKLER,
        "acik_sayi": sum(sayilar[d] for d in Is.ACIK), "dis_erisim": dis_erisim_mi(request)})


def _islem(request):
    islem = request.POST.get("islem")
    if islem == "ekle":
        baslik = request.POST.get("baslik", "").strip()
        if not baslik:
            messages.error(request, "İşin başlığını yazın.")
            return redirect("isler:liste")
        oncelik = request.POST.get("oncelik")
        i = Is.objects.create(baslik=baslik[:200], aciklama=request.POST.get("aciklama", "").strip(),
                              oncelik=oncelik if oncelik in dict(Is.ONCELIKLER) else Is.NORMAL,
                              dis_erisim=dis_erisim_mi(request), olusturan=request.user)
        messages.success(request, f"İş eklendi: #{i.pk} {i.baslik}. Claude bir sonraki kontrolde ele alır.")
        return redirect("isler:liste")
    i = get_object_or_404(Is, pk=request.POST.get("pk") or 0)
    metin = request.POST.get("metin", "").strip()
    if islem == "onayla" and i.durum == Is.ONAY:
        i.onaylandi = True
        i.save(update_fields=["onaylandi", "guncelleme"])
        IsNotu.objects.create(is_kaydi=i, yazan=request.user, metin=metin or "Onaylandı.")
        messages.success(request, f"#{i.pk} onaylandı; Claude bir sonraki kontrolde tamamlar.")
    elif islem == "cevap" and metin:
        servis.durum_degistir(i, Is.BEKLIYOR if i.durum in (Is.SORU, Is.ONAY) else i.durum, metin, request.user)
        messages.success(request, f"#{i.pk} için notunuz eklendi.")
    elif islem == "iptal" and i.acik:
        servis.durum_degistir(i, Is.IPTAL, metin or "İptal edildi.", request.user)
        messages.info(request, f"#{i.pk} iptal edildi.")
    elif islem == "yeniden_ac" and not i.acik:
        servis.durum_degistir(i, Is.BEKLIYOR, metin or "Yeniden açıldı.", request.user)
        messages.info(request, f"#{i.pk} yeniden açıldı.")
    elif islem == "sil" and i.durum == Is.BEKLIYOR and not i.notlar.filter(claude=True).exists():
        i.delete()
        messages.info(request, "İş silindi.")
    else:
        messages.error(request, "Bu işlem şu an yapılamaz.")
    return redirect(request.POST.get("geri") or "isler:liste")
