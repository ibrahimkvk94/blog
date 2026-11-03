"""KAMYOSİS yetkilerinden Ders Programı modülü üyeliklerinin (Membership) üretilmesi.

Modülde kullanıcı ve yetki yönetimi kapalıdır; üyelikler yalnızca buradan yazılır.

| KAMYOSİS etkin yetki ("program-hazirlama") | Modül yetkileri                                         |
|--------------------------------------------|---------------------------------------------------------|
| Görüntüleme ya da kapsamı "bölüm" olan     | yalnız görüntüleme                                      |
| Düzenleme (tüm)                            | veri girişi, etkinlik ve telafi                         |
| Yönetim (tüm)                              | + program üretme, yayınlama, program ekleme ve silme    |

"Sınav Planları" yetkisi olan kullanıcıya da en az görüntüleme üyeliği verilir; sınav işlemlerindeki
yetkiyi köprü ara katmanı ayrıca verir (middleware.py).
"""

from types import SimpleNamespace

from django.conf import settings
from django.contrib.auth import get_user_model

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from timetable.models import Institution, Membership as M

PROGRAM_BIRIMI = "program-hazirlama"
SINAV_BIRIMI = "sinav-planlari"

MODUL_YETKILERI = {
    GORUNTULEME: [],
    DUZENLEME: [M.DATA, M.SUBSTITUTE],  # SUBSTITUTE: etkinlik ve telafi kaydı (vekâlet sayfası kapalı)
    YONETIM: [M.DATA, M.SUBSTITUTE, M.PROGRAM, M.PUBLISH, M.PROGRAMS],
}


def kurum():
    """Modüldeki tek kurum: ilk kayıt; yoksa kurum adıyla açılır."""
    return Institution.objects.order_by("pk").first() or Institution.objects.create(name=settings.KURUM_ADI)


def birim_yetkisi(user, slug):
    """Kullanıcının bir birimdeki etkin yetkisi (seviye, kapsam); birim yoksa (0, None)."""
    sahte = SimpleNamespace(user=user)  # core.yetki ağacı ve yetki tablosunu bu nesneye önbellekler
    try:
        return etkin_yetki(sahte, birim_bul(sahte, slug))
    except Exception:  # Http404: birim yok ya da pasif
        return (0, None)


def modul_yetkileri(user):
    """(yetki listesi, açabildiği modüller) ya da üyelik gerekmiyorsa None.

    Modüller: Program Hazırlama yetkisi → Ders Planlama ("ders"), Sınav Planları yetkisi → Sınav Planlama ("sinav").
    Sınav işlemlerinin yetkisi üyelikten değil, ara katmanın Sınav Planları denetiminden gelir.
    """
    if not user.is_active or user.is_superuser:
        return None  # süper kullanıcıya modül zaten her şeyi verir
    seviye, kapsam = birim_yetkisi(user, PROGRAM_BIRIMI)
    sinav = birim_yetkisi(user, SINAV_BIRIMI)[0] >= GORUNTULEME
    moduller = (["ders"] if seviye >= GORUNTULEME else []) + (["sinav"] if sinav else [])
    if not moduller:
        return None
    if seviye >= GORUNTULEME and kapsam != Yetki.BOLUM:
        return list(MODUL_YETKILERI[seviye]), moduller
    return [], moduller


def esitle(user):
    k = kurum()
    sonuc = modul_yetkileri(user)
    if sonuc is None:
        M.objects.filter(user=user, institution=k).delete()
        return
    yetkiler, moduller = sonuc
    uyelik, yeni = M.objects.get_or_create(user=user, institution=k, defaults={"permissions": yetkiler, "modules": moduller})
    if not yeni and (uyelik.permissions != yetkiler or uyelik.modules != moduller):
        uyelik.permissions, uyelik.modules = yetkiler, moduller
        uyelik.save(update_fields=["permissions", "modules"])
    # Kurum dışı üyelikler ve program kısıtları KAMYOSİS'te kullanılmaz
    M.objects.filter(user=user).exclude(institution=k).delete()
    uyelik.programs.clear()


def hepsini_esitle():
    for user in get_user_model().objects.all():
        esitle(user)
