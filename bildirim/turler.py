"""Bildirim türleri ve alıcıları. Alıcılar kişi listesiyle değil yetkiyle belirlenir: "Kullanıcılar ve yetkiler"
sayfasında ilgili modülün yetkisini alan hesap o türün bildirimlerini de alır (sistem yöneticileri hepsini)."""

from dataclasses import dataclass, field

from django.contrib.auth import get_user_model

from core.models import Birim, Yetki

GORUNTULEME, DUZENLEME, YONETIM = Yetki.GORUNTULEME, Yetki.DUZENLEME, Yetki.YONETIM


@dataclass(frozen=True)
class Tur:
    kod: str
    ad: str
    ikon: str          # Bootstrap Icons adı
    renk: str          # bildirim-ikon renk sınıfı: mor, sari, yesil, mavi, turuncu, gri
    kimler: str        # ayarlar ekranındaki açıklama
    birimler: tuple = field(default=())  # (birim slug, en az seviye, yalnız tüm okul kapsamı)


TURLER = {t.kod: t for t in [
    Tur("vekalet", "Vekâlet girildi / değişti", "person-up", "mor",
        "İdari İşler ve vekâlet verenin birimi",
        (("vekalet", DUZENLEME, False),)),
    Tur("mazeret_teslimi", "Bölüm mazeretlerini kesinleştirdi", "send-check", "sari",
        "Mazeretleri yöneten (Plan Program)",
        (("sinav-mazeretleri", YONETIM, True), ("ders-mazeretleri", YONETIM, True))),
    Tur("yoklama_ozeti", "Yoklama özeti (09.30 ve 14.00)", "clipboard-check", "yesil",
        "Personel yoklamasını yöneten (İdari İşler)",
        (("personel-yoklamasi", YONETIM, True),)),
    Tur("ders_programi", "Ders programı yayınlandı", "calendar3", "mavi",
        "Ders planlarını görebilen herkes",
        (("ders-planlari", GORUNTULEME, False),)),
    Tur("sinav_programi", "Sınav programı yayınlandı", "calendar-check", "turuncu",
        "Sınav planlarını görebilen herkes",
        (("sinav-planlari", GORUNTULEME, False),)),
    Tur("nobet", "Nöbet grupları kesinleşti", "shield-check", "gri",
        "Nöbet gruplarını görebilen herkes",
        (("nobet-gruplari", GORUNTULEME, False),)),
]}


def yetkililer(slug, en_az=GORUNTULEME, tum_okul=False):
    """{kullanıcı id: (seviye, kapsam)}: birimde (üst birimlerden gelen dahil) en az `en_az` yetkisi olan etkin
    hesaplar (core.yetki.etkin_yetki ile aynı kural) ve sistem yöneticileri."""
    birimler = {b.pk: b for b in Birim.objects.filter(aktif=True)}
    hedef = next((b for b in birimler.values() if b.slug == slug), None)
    out = {}
    if hedef is not None and hedef.durum == Birim.KULLANIMDA:
        zincir, d = [], hedef
        while d is not None:
            zincir.append(d.pk)
            d = birimler.get(d.ust_id)
        for y in Yetki.objects.filter(birim_id__in=zincir, kullanici__is_active=True).only(
                "kullanici_id", "seviye", "kapsam"):
            eski = out.get(y.kullanici_id, (0, None))
            if y.seviye > eski[0] or (y.seviye == eski[0] and y.kapsam == Yetki.TUM):
                out[y.kullanici_id] = (y.seviye, y.kapsam)
        out = {k: v for k, v in out.items() if v[0] >= en_az and (not tum_okul or v[1] == Yetki.TUM)}
    for pk in get_user_model().objects.filter(is_active=True, is_superuser=True).values_list("pk", flat=True):
        out[pk] = (YONETIM, Yetki.TUM)
    return out


def alabilenler(tur):
    """Türün bildirimini alabilecek hesapların kimlikleri (kapsam ayrıntısı olay anında ayrıca süzülür)."""
    idler = set()
    for slug, en_az, tum in tur.birimler:
        idler |= set(yetkililer(slug, en_az, tum))
    return idler


def kullanicinin_turleri(user):
    return [t for t in TURLER.values() if user.pk in alabilenler(t)]
