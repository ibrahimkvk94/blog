from django.conf import settings
from django.http import Http404
from django.urls import reverse

from .yetki import GORUNTULEME, birim_bul, etkin_yetki, menu_agaci


def _kisayollar(request):
    """Sık kullanılan sayfalar; kullanıcının yetkisi olanlar."""
    sonuc = []
    try:
        ders = etkin_yetki(request, birim_bul(request, "ders-planlari"))[0] >= GORUNTULEME
        personel = etkin_yetki(request, birim_bul(request, "personel-bilgileri"))[0] >= GORUNTULEME
    except Http404:
        return sonuc
    if ders:
        sonuc += [
            ("takip:gunluk", "Ders takibi", "check2-square"),
            ("program:tablo", "Haftalık program", "table"),
            ("takip:devirler", "Devir talepleri", "arrow-left-right"),
        ]
    try:
        if etkin_yetki(request, birim_bul(request, "ders-mazeretleri"))[0] >= GORUNTULEME:
            sonuc.append(("mazeret:ders", "Ders mazeretleri", "calendar-x"))
    except Http404:
        pass
    if personel:
        sonuc.append(("personel:liste", "Personel", "person-vcard"))
    return [{"url": reverse(ad), "ad": etiket, "ikon": ikon, "ad_kodu": ad} for ad, etiket, ikon in sonuc]


def navigation(request):
    ctx = {"kurum_adi": settings.KURUM_ADI, "sistem_adi": settings.SISTEM_ADI}
    if request.user.is_authenticated and not request.path.startswith("/yonetim/"):
        ctx["menu"] = menu_agaci(request)
        ctx["kisayollar"] = _kisayollar(request)
    return ctx
