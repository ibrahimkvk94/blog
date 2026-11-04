"""Menüdeki kısayollar.

Kısayol, kullanıcının ilgili birimde görüntüleme yetkisi varsa görünür. Bölüm hesaplarının menüsünde yalnızca
kısayollar bulunur (birim ağacı ve organizasyon şeması gizlidir); hangi kısayolu göreceklerini sistem yöneticisi
bölüm bölüm seçer ("Bölüm kısayolları", BolumMenusu). Kapatılan kısayolun sayfaları o bölüme kapanır
(BolumKisayolMiddleware: menü, ana sayfa kartı ya da adres yazarak erişilemez).
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
    ("personel-yoklamasi", "yoklama:ana", "Personel yoklaması", "person-check", "personel-yoklamasi"),
]
# Kısayolun kapsadığı sayfalar: {kod: [(ad alanı, adlar ya da None = ad alanının tümü)]}
ADRESLER = {
    "ders-takibi": [("takip", {"gunluk", "rapor"})],
    "haftalik-program": [("program", None)],
    "devir-talepleri": [("takip", {"devir_yeni", "devirler", "devir_karar"})],
    "ders-mazeretleri": [("mazeret", {"ders", "bildirim", "toplu", "aktar"})],
    "sinav-mazeretleri": [("mazeret", {"sinav", "sinav_bildirim", "sinav_toplu", "sinav_aktar"})],
    "sinav-planlari": [("dersprogrami_kopru", {"sinavlar"}), ("sinav", None)],
    "sinav-gorev-puantaji": [("sinavgorev", None)],
    "personel": [("personel", None)],
    "personel-yoklamasi": [("yoklama", None)],
}
# Bölüm hesapları dışındaki kullanıcıların menüsünde de bulunan kısayollar (eski düzen)
GENEL = {"ders-takibi", "haftalik-program", "devir-talepleri", "ders-mazeretleri", "sinav-mazeretleri", "personel",
         "personel-yoklamasi"}


def bolum_hesabi_mi(user):
    """Bölüm hesabı: sistem yöneticisi değil, bir bölüme bağlı ve "tüm bölümler" kapsamlı yetkisi yok
    (bolum_yetkileri.bolum_hesaplari ile aynı tanım)."""
    if not user.is_authenticated or user.is_superuser or user.bolum_id is None:
        return False
    if not hasattr(user, "_tum_kapsam"):
        user._tum_kapsam = user.yetkiler.filter(kapsam=Yetki.TUM).exists()
    return not user._tum_kapsam


def gizli_kodlar(user):
    """Bölüm hesabı için kapatılmış kısayollar; diğer kullanıcılar için boş küme."""
    if not bolum_hesabi_mi(user):
        return set()
    if not hasattr(user, "_gizli_kisayollar"):
        ayar = BolumMenusu.objects.filter(bolum_id=user.bolum_id).first()
        user._gizli_kisayollar = set(ayar.gizli) if ayar else set()
    return user._gizli_kisayollar


def adres_kodu(eslesme):
    """Adres eşleşmesinin (resolver_match) ait olduğu kısayol kodu; yoksa None."""
    if eslesme is None:
        return None
    for kod, kurallar in ADRESLER.items():
        for alan, adlar in kurallar:
            if eslesme.namespace == alan and (adlar is None or eslesme.url_name in adlar):
                return kod
    return None


def kapali_mi(user, eslesme):
    kod = adres_kodu(eslesme)
    return kod is not None and kod in gizli_kodlar(user)


def _gorur(request, slug):
    try:
        return etkin_yetki(request, birim_bul(request, slug))[0] >= GORUNTULEME
    except Http404:
        return False


def kisayollar(request):
    """[{"url", "ad", "ikon", "ad_kodu", "kod"}] — kullanıcının menüsündeki kısayollar."""
    bolum = bolum_hesabi_mi(request.user)
    gizli = gizli_kodlar(request.user)
    out = []
    for kod, ad_kodu, etiket, ikon, slug in KISAYOLLAR:
        if (not bolum and kod not in GENEL) or kod in gizli or not _gorur(request, slug):
            continue
        out.append({"url": reverse(ad_kodu), "ad": etiket, "ikon": ikon, "ad_kodu": ad_kodu, "kod": kod})
    return out
