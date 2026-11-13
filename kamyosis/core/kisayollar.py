"""Menüdeki kısayollar ve bölümlere kapatılan sayfalar.

Kısayollar (09.11.2026): kullanıcı menüde bir sayfanın yanındaki yıldıza tıklayarak onu kısayollarına ekler
(Kisayol); menünün "Kısayollar" bölümünde ve ana sayfadaki "Sık kullanılanlar"da yalnız bunlar görünür. Yetkisi
kalkan ya da bölümüne kapatılan sayfanın yıldızı gösterilmez.

Bölüme kapatılan sayfalar: sistem yöneticisi bölüm bölüm bazı sayfaları kapatabilir ("Bölüm kısayolları",
BolumMenusu; aşağıdaki KISAYOLLAR kodları). Kapatılan sayfa o bölümün menüsünde görünmez ve açılamaz
(BolumKisayolMiddleware: menü, ana sayfa kartı ya da adres yazarak erişilemez).
"""

from django.urls import resolve

from .models import BolumMenusu, Kisayol, Yetki
from .yetki import HERKESE_ACIK, agac, gorunur_mu

# (kod, adres adı, etiket, ikon, yetkinin bakıldığı birim)
KISAYOLLAR = [
    ("ders-takibi", "takip:gunluk", "Ders takibi", "check2-square", "ders-takibi"),
    ("haftalik-program", "program:tablo", "Haftalık program", "table", "ders-planlari"),
    ("devir-talepleri", "takip:devirler", "Devir talepleri", "arrow-left-right", "devir-talepleri"),
    ("ders-mazeretleri", "mazeret:ders", "Ders mazeretleri", "calendar-x", "ders-mazeretleri"),
    ("sinav-mazeretleri", "mazeret:sinav", "Sınav mazeretleri", "calendar2-x", "sinav-mazeretleri"),
    ("sinav-planlari", "dersprogrami_kopru:sinavlar", "Sınav planları", "clipboard-check", "sinav-planlari"),
    ("sinav-gorev-puantaji", "sinavgorev:puantaj", "Sınav görev puantajı", "clipboard-data", "sinav-gorev-puantaji"),
    ("personel", "personel:liste", "Personel kartları", "person-vcard", "personel-bilgileri"),
    ("personel-yoklamasi", "yoklama:ana", "Personel yoklaması", "person-check", "personel-yoklamasi"),
    ("salon-durumu", "salon:yil", "Salon durumu", "calendar-week", None),  # None: herkes görür
]
# Kısayolun kapsadığı sayfalar: {kod: [(ad alanı, adlar ya da None = ad alanının tümü)]}
ADRESLER = {
    "ders-takibi": [("takip", {"gunluk", "rapor"})],
    "haftalik-program": [("program", None)],
    "devir-talepleri": [("takip", {"devir_yeni", "devirler", "devir_karar"})],
    "ders-mazeretleri": [("mazeret", {"ders", "bildirim", "toplu", "aktar"})],
    "sinav-mazeretleri": [("mazeret", {"sinav", "sinav_bildirim", "sinav_toplu", "sinav_aktar"})],
    "sinav-planlari": [("dersprogrami_kopru", {"sinavlar", "sinav_programi", "sinav_programi_donem",
                                               "sinav_programi_excel", "sinav_yayini"}), ("sinav", None)],
    "sinav-gorev-puantaji": [("sinavgorev", None)],
    "personel": [("personel", None)],
    "personel-yoklamasi": [("yoklama", None)],
    "salon-durumu": [("salon", None)],
}


def bolum_hesabi_mi(user):
    """Bölüm ya da birim hesabı: sistem yöneticisi değil, bir bölüme ya da teşkilat birimine (şube müdürlüğü, kısım)
    bağlı ve "tüm bölümler" kapsamlı yetkisi yok. Ana sayfasında "Tüm birimler" kartı yoktur. (Bölüm yetkileri
    sayfasındaki bolum_yetkileri.bolum_hesaplari yalnız bölüme bağlı olanları alır.)"""
    if not user.is_authenticated or user.is_superuser or (user.bolum_id is None and user.teskilat_birimi_id is None):
        return False
    if not hasattr(user, "_tum_kapsam"):
        user._tum_kapsam = user.yetkiler.filter(kapsam=Yetki.TUM).exists()
    return not user._tum_kapsam


def gizli_kodlar(user):
    """Bölüm hesabı için kapatılmış kısayollar; diğer kullanıcılar için boş küme."""
    if not bolum_hesabi_mi(user) or user.bolum_id is None:  # birim hesaplarında kapatılan kısayol yok
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


def birim_kapali_mi(user, birim):
    """Birimin sayfası bu bölüme kapatılmış mı (BolumMenusu)."""
    gizli = gizli_kodlar(user)
    if not gizli or not birim.modul_url:
        return False
    try:
        return adres_kodu(resolve(birim.get_absolute_url())) in gizli
    except Exception:  # adres çözülemezse kapatma kuralı uygulanmaz
        return False


def menuden_ayikla(user, dugumler):
    """Bölüme kapatılmış sayfaları menü ağacından çıkarır (alt dalı boşalan başlık da gider)."""
    if not gizli_kodlar(user):
        return dugumler
    out = []
    for d in dugumler:
        if d.menu_cocuklar:
            d.menu_cocuklar = menuden_ayikla(user, d.menu_cocuklar)
            if d.menu_cocuklar:
                out.append(d)
        elif not birim_kapali_mi(user, d):
            out.append(d)
    return out


def yildizli_idler(request):
    """Kullanıcının yıldızladığı birimlerin kimlikleri (istek başına bir kez okunur)."""
    if not hasattr(request, "_yildizli"):
        request._yildizli = (list(Kisayol.objects.filter(kullanici=request.user).values_list("birim_id", flat=True))
                             if request.user.is_authenticated else [])
    return request._yildizli


def yildizlanabilir_mi(request, birim):
    """Yıldız yalnız sayfası olan (alt birimi olmayan) ve kullanıcının açabildiği birimlere konur."""
    if birim.cocuklar or birim_kapali_mi(request.user, birim):
        return False
    acik = birim.slug in HERKESE_ACIK and birim.durum == birim.KULLANIMDA and request.user.is_authenticated
    return acik or gorunur_mu(request, birim)


def acik_sayfalar(request):
    """Herkese açık olup ağaçta görünmeyen sayfalar (menünün başında sabit durur)."""
    by_id, _ = agac(request)
    out = []
    for b in by_id.values():
        if b.slug in HERKESE_ACIK and not gorunur_mu(request, b) and yildizlanabilir_mi(request, b):
            out.append(b)
    return out


def kisayollar(request):
    """[{"url", "ad", "ikon", "birim"}] — kullanıcının yıldızladığı ve hâlâ açabildiği sayfalar (eklediği sırayla)."""
    by_id, _ = agac(request)
    out = []
    for bid in yildizli_idler(request):
        b = by_id.get(bid)
        if b is None or not yildizlanabilir_mi(request, b):
            continue
        out.append({"url": b.get_absolute_url(), "ad": b.ad, "ikon": b.ikon, "birim": b})
    return out
