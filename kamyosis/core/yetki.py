"""Organizasyon ağacı üzerinden yetki hesaplama.

Ağaç ve kullanıcının yetkileri istek başına bir kez yüklenir. Bir birime verilen
yetki tüm alt birimlere geçer; kullanıcı, yetkisi olan bir alt birime giden
yoldaki üst birimleri de menüde görür.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404

from .models import Birim, Yetki

GORUNTULEME, DUZENLEME, YONETIM = Yetki.GORUNTULEME, Yetki.DUZENLEME, Yetki.YONETIM
# Sayfası herkese açık birimler: ağaçta göremeyenlerin menüsünün başında da durur ve yıldızlanabilir (yetki hesabını
# değiştirmez; düzenleme yine yetki ister). Salon durumu: okulun salon takvimi herkese açık, kaydı Plan Program girer.
# Sınav icrası: ilk sekmesi sınav takvimi (yayınlanan ara sınav / final planları) herkese açık, planı yetkililer yükler.
HERKESE_ACIK = ("salon-durumu", "sinav-icrasi")


def agac(request):
    """(id -> birim, kök birimler) döner. Pasif birimler ve altları gizlenir."""
    if not hasattr(request, "_birim_agaci"):
        birimler = list(Birim.objects.filter(aktif=True).order_by("sira", "ad"))
        by_id = {b.id: b for b in birimler}
        kokler = []
        for b in birimler:
            b.cocuklar = []
        for b in birimler:
            if b.ust_id is None:
                kokler.append(b)
            elif b.ust_id in by_id:
                by_id[b.ust_id].cocuklar.append(b)
        request._birim_agaci = (by_id, kokler)
    return request._birim_agaci


def _yetkiler(request):
    if not hasattr(request, "_yetki_tablosu"):
        request._yetki_tablosu = {
            y.birim_id: (y.seviye, y.kapsam) for y in Yetki.objects.filter(kullanici=request.user)
        }
    return request._yetki_tablosu


def etkin_yetki(request, birim):
    """Birim ve üstlerindeki en yüksek yetki: (seviye, kapsam). Yetki yoksa (0, None)."""
    user = request.user
    if not user.is_authenticated or not user.is_active:
        return (0, None)
    if user.is_superuser:
        return (YONETIM, Yetki.TUM)
    by_id, _ = agac(request)
    yetkiler = _yetkiler(request)
    en_iyi = (0, None)
    dugum = by_id.get(birim.id, birim)
    while dugum is not None:
        y = yetkiler.get(dugum.id)
        if y and (y[0] > en_iyi[0] or (y[0] == en_iyi[0] and y[1] == Yetki.TUM)):
            en_iyi = y
        dugum = by_id.get(dugum.ust_id)
    return en_iyi


def gorunur_cocuklar(request, birim):
    return [c for c in birim.cocuklar if _gorunur(request, c)]


def _gorunur(request, birim):
    if not birim.cocuklar:
        # Henüz hazır olmayan modüller sadece sistem yöneticisine görünür
        if birim.durum != Birim.KULLANIMDA and not request.user.is_superuser:
            return False
        return etkin_yetki(request, birim)[0] >= GORUNTULEME
    return any(_gorunur(request, c) for c in birim.cocuklar)


def gorunur_mu(request, birim):
    by_id, _ = agac(request)
    return _gorunur(request, by_id.get(birim.id, birim))


def menu_agaci(request):
    """Kullanıcının görebileceği kök birimler; her düğümde `menu_cocuklar` ve `acik` alanları olur."""
    _, kokler = agac(request)
    aktif = getattr(request, "birim", None)
    acik_idler = {b.id for b in yol(request, aktif)} if aktif else set()

    def filtrele(dugumler):
        sonuc = []
        for d in dugumler:
            d.menu_cocuklar = filtrele(d.cocuklar)
            if d.menu_cocuklar or (not d.cocuklar and _gorunur(request, d)):
                d.acik = d.id in acik_idler
                d.secili = aktif is not None and d.id == aktif.id
                sonuc.append(d)
        return sonuc

    return filtrele(kokler)


def yol(request, birim):
    """Kökten verilen birime kadar olan birimler (breadcrumb için)."""
    by_id, _ = agac(request)
    sonuc = []
    dugum = by_id.get(birim.id, birim)
    while dugum is not None:
        sonuc.append(dugum)
        dugum = by_id.get(dugum.ust_id)
    return list(reversed(sonuc))


def birim_bul(request, slug):
    by_id, _ = agac(request)
    for b in by_id.values():
        if b.slug == slug:
            return b
    raise Http404("Birim bulunamadı.")


def yetki_gerekli(slug, seviye=GORUNTULEME):
    """Görünümü bir birime bağlar. request.birim, request.yetki_seviye, request.yetki_kapsam ayarlanır."""

    def dekorator(view):
        @wraps(view)
        def sarmal(request, *args, **kwargs):
            birim = birim_bul(request, slug)
            s, kapsam = etkin_yetki(request, birim)
            if s < seviye:
                raise PermissionDenied
            request.birim, request.yetki_seviye, request.yetki_kapsam = birim, s, kapsam
            return view(request, *args, **kwargs)

        return login_required(sarmal)

    return dekorator
