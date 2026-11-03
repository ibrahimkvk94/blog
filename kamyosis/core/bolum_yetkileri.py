"""Bölüm hesaplarının modül yetkileri tablosu: satır = bölüm, sütun = kullanımdaki modül.

Bölüm hesabı: bölümü atanmış, sistem yöneticisi olmayan ve "tüm bölümler" kapsamlı hiçbir
yetkisi bulunmayan etkin kullanıcı. Bir bölümün birden çok hesabı varsa satır hepsine uygulanır.
Kaydederken bu hesapların modüllere ve onların üst birimlerine verilmiş yetkileri modül
düzeyindeki "kendi bölümü" yetkileriyle değiştirilir (üst birim yetkisi tüm alt modüllere geçtiği için).
"""

from collections import OrderedDict

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import Birim, Yetki

GORUR, DUZENLER = Yetki.GORUNTULEME, Yetki.DUZENLEME
SEVIYELER = [(GORUR, "Görür"), (DUZENLER, "Düzenler")]
# Bölüm hesabı bu modüllerde zaten yalnızca görür (köprü kendi bölümü kapsamını salt okunur sayar).
YALNIZ_GORUR = {"program-hazirlama"}


def bolum_hesaplari():
    User = get_user_model()
    return list(
        User.objects.filter(is_active=True, is_superuser=False).exclude(bolum=None)
        .exclude(yetkiler__kapsam=Yetki.TUM).select_related("bolum").prefetch_related("yetkiler")
        .order_by("bolum__ad", "username")
    )


def _agac():
    birimler = list(Birim.objects.filter(aktif=True).order_by("sira", "ad"))
    by_id = {b.id: b for b in birimler}
    for b in birimler:
        b.cocuklar = []
    kokler = []
    for b in birimler:
        if b.ust_id is None:
            kokler.append(b)
        elif b.ust_id in by_id:
            by_id[b.ust_id].cocuklar.append(b)
    return by_id, kokler


def moduller():
    """Kullanımdaki yaprak birimler, ağaç sırasıyla; her birinde `grup` ve `ataler` (kökten kendisine).

    grup: kökün bir altındaki birim (ör. Plan Program Kısmı); modül doğrudan kökün altındaysa kök (ör. İdari İşler).
    """
    by_id, kokler = _agac()
    sonuc = []

    def gez(dugum, ataler):
        ataler = ataler + [dugum.id]
        if not dugum.cocuklar:
            if dugum.durum == Birim.KULLANIMDA:
                dugum.grup = by_id[ataler[1] if len(ataler) > 2 else ataler[0]]
                dugum.ataler = ataler
                sonuc.append(dugum)
            return
        for c in dugum.cocuklar:
            gez(c, ataler)

    for k in kokler:
        gez(k, [])
    return sonuc


def _etkin(yetkiler, modul):
    """Kullanıcının modüldeki (üst birimlerden miras dahil) en yüksek seviyesi."""
    return max((y.seviye for y in yetkiler if y.birim_id in modul.ataler), default=0)


def tablo():
    """(modüller, satırlar, sütun seviyeleri). Satır: bölüm, hesaplar, {modül id: (görür mü, hesaplar arasında fark var mı)}."""
    mods = moduller()
    hesaplar = bolum_hesaplari()
    satirlar = OrderedDict()
    for u in hesaplar:
        satirlar.setdefault(u.bolum_id, {"bolum": u.bolum, "hesaplar": []})["hesaplar"].append(u)
    sutun_seviye = {}
    for m in mods:
        seviyeler = [_etkin(list(u.yetkiler.all()), m) for u in hesaplar]
        en_yuksek = max(seviyeler, default=0)
        sutun_seviye[m.id] = GORUR if m.slug in YALNIZ_GORUR else min(max(en_yuksek, GORUR), DUZENLER)
    for s in satirlar.values():
        s["hucreler"] = []
        for m in mods:
            var = [_etkin(list(u.yetkiler.all()), m) >= GORUR for u in s["hesaplar"]]
            s["hucreler"].append({"modul": m, "gorur": any(var), "fark": any(var) and not all(var)})
    return mods, list(satirlar.values()), sutun_seviye


@transaction.atomic
def kaydet(secim, sutun_seviye):
    """secim: {bölüm id: {modül id, ...}}; sutun_seviye: {modül id: seviye}. Dönüş: değişen yetki sayısı."""
    mods = {m.id: m for m in moduller()}
    ilgili = set()
    for m in mods.values():
        ilgili.update(m.ataler)
    degisen = 0
    for u in bolum_hesaplari():
        hedef = {}
        for mid in secim.get(u.bolum_id, ()):
            if mid in mods:
                s = GORUR if mods[mid].slug in YALNIZ_GORUR else sutun_seviye.get(mid, GORUR)
                hedef[mid] = s if s in (GORUR, DUZENLER) else GORUR
        for y in [y for y in u.yetkiler.all() if y.birim_id in ilgili]:
            if hedef.get(y.birim_id) == y.seviye and y.kapsam == Yetki.BOLUM:
                del hedef[y.birim_id]  # zaten istenen gibi
            else:
                y.delete()  # sinyal: modül üyeliği eşitlenir
                degisen += 1
        for mid, s in hedef.items():
            Yetki.objects.create(kullanici=u, birim_id=mid, seviye=s, kapsam=Yetki.BOLUM)
            degisen += 1
    return degisen
