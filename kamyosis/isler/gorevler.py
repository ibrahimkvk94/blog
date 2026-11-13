"""Ana sayfadaki "Yapılacaklar" kutusu: iş listesi sahibine Claude'dan gelen soru ve onay istekleri."""

from django.urls import reverse

from . import servis
from .models import Is


def panel_gorevleri(request):
    if not servis.sahibi_mi(request.user):
        return []
    out = []
    soru = Is.objects.filter(durum=Is.SORU).count()
    onay = Is.objects.filter(durum=Is.ONAY, onaylandi=False).count()
    if soru:
        out.append({"renk": "eksik", "ikon": "chat-left-dots", "sayi": soru, "ad": "Claude'un sorusu var",
                    "aciklama": "İş listesi", "url": reverse("isler:liste")})
    if onay:
        out.append({"renk": "eksik", "ikon": "shield-check", "sayi": onay, "ad": "Onayınızı bekleyen iş",
                    "aciklama": "İş listesi", "url": reverse("isler:liste")})
    return out
