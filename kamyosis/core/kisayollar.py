"""Menüdeki kısayollar.

Kısayol, kullanıcının ilgili birimde görüntüleme yetkisi varsa görünür. Bölüm hesaplarının menüsünde yalnızca
kısayollar bulunur (birim ağacı ve organizasyon şeması gizlidir); hangi kısayolu göreceklerini sistem yöneticisi
bölüm bölüm seçer ("Bölüm kısayolları", BolumMenusu). Gizlemek yalnızca menüyü etkiler, yetkiyi değiştirmez.
"""

from django.http import Http404
from django.urls import reverse

from .models import BolumMenusu, Yetki
from .yetki import GORUNTULEME, birim_bul, etkin_yetki

# (kod, adres adı, etiket, ikon, yetkinin bakıldığı birim)
KISAYOLLAR = [
    ("ders-takibi", "takip:gunluk", "Ders takibi", "check2-square", "ders-planlari"),
    ("haftalik-program", "program:tablo", "Haftalık program", "table", "ders-planlari"),
    ("devir-talepleri", "takip:devirler", "Devir talepleri", "arrow-left-right", "ders-planlari"),
    ("ders-mazeretleri", "mazeret:ders", "Ders mazeretleri", "calendar-x", "ders-mazeretleri"),
    ("sinav-mazeretleri", "mazeret:sinav", "Sınav mazeretleri", "calendar2-x", "sinav-mazeretleri"),
    ("sinav-planlari", "dersprogrami_kopru:sinavlar", "Sınav planları", "clipboard-check", "sinav-planlari"),
    ("sinav-gorev-puantaji", "sinavgorev:puantaj", "Sınav görev puantajı", "clipboard-data", "sinav-gorev-puantaji"),
    ("personel", "personel:liste", "Personel", "person-vcard", "personel-bilgileri"),
]
# Bölüm hesapları dışındaki kullanıcıların menüsünde de bulunan kısayollar (eski düzen)
GENEL = {"ders-takibi", "haftalik-program", "devir-talepleri", "ders-mazeretleri", "sinav-mazeretleri", "personel"}


def bolum_hesabi_mi(user):
    """Bölüm hesabı: sistem yöneticisi değil, bir bölüme bağlı ve "tüm bölümler" kapsamlı yetkisi yok
    (bolum_yetkileri.bolum_hesaplari ile aynı tanım)."""
    if not user.is_authenticated or user.is_superuser or user.bolum_id is None:
        return False
    if not hasattr(user, "_tum_kapsam"):
        user._tum_kapsam = user.yetkiler.filter(kapsam=Yetki.TUM).exists()
    return not user._tum_kapsam


def _gorur(request, slug):
    try:
        return etkin_yetki(request, birim_bul(request, slug))[0] >= GORUNTULEME
    except Http404:
        return False


def kisayollar(request):
    """[{"url", "ad", "ikon", "ad_kodu", "kod"}] — kullanıcının menüsündeki kısayollar."""
    bolum = bolum_hesabi_mi(request.user)
    gizli = set()
    if bolum:
        ayar = BolumMenusu.objects.filter(bolum_id=request.user.bolum_id).first()
        gizli = set(ayar.gizli) if ayar else set()
    out = []
    for kod, ad_kodu, etiket, ikon, slug in KISAYOLLAR:
        if (not bolum and kod not in GENEL) or kod in gizli or not _gorur(request, slug):
            continue
        out.append({"url": reverse(ad_kodu), "ad": etiket, "ikon": ikon, "ad_kodu": ad_kodu, "kod": kod})
    return out
