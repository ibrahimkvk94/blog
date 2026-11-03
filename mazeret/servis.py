"""Ders mazereti iş kuralları.

- Bölüm kapsamlı kullanıcı yalnızca kendi bölümünün personelini görür ve bildirir.
- Düzenleme yetkisi bildirim yapar; dönem kapalıysa ya da son bildirim zamanı geçtiyse
  yalnızca yönetim yetkisi değiştirebilir.
- Kaydetme iyimser kilitle yapılır: başkası araya girdiyse kayıt reddedilir.
- Dönem bir Program Hazırlama programına bağlıysa her kayıt o programdaki öğretmenin
  müsaitliğini değiştirir (öğretmen ad soyadla eşleştirilir; T.C. kimlik no kullanılmaz).
"""

from dataclasses import dataclass

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from dersprogrami_kopru.kunye import ogretmen_eslesmesi
from personel.models import Personel

from .models import DURUMLAR, DersMazeretBildirimi, DersMazeretGecmisi

BIRIM_DERS = "ders-mazeretleri"


class MazeretHatasi(Exception):
    pass


@dataclass
class MazeretYetkisi:
    goruntule: bool = False
    bildir: bool = False
    yonetim: bool = False
    kapsam_bolum: object = None     # None = tüm bölümler

    def kapsar(self, personel):
        return self.kapsam_bolum is None or personel.bolum_id == self.kapsam_bolum.pk


def yetki(request):
    if hasattr(request, "_mazeret_yetkisi"):
        return request._mazeret_yetkisi
    y = MazeretYetkisi()
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM_DERS))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule, y.bildir, y.yonetim = seviye >= GORUNTULEME, seviye >= DUZENLEME, seviye >= YONETIM
    if kapsam == Yetki.BOLUM:
        y.kapsam_bolum = request.user.bolum
        if y.kapsam_bolum is None:  # bölümü atanmamış bölüm kullanıcısı hiçbir şeyi kapsamaz
            y.goruntule = y.bildir = y.yonetim = False
    request._mazeret_yetkisi = y
    return y


def personeller(y, bolum=None):
    qs = Personel.objects.filter(aktif=True).select_related("bolum", "unvan", "rutbe", "sinif")
    if y.kapsam_bolum is not None:
        qs = qs.filter(bolum=y.kapsam_bolum)
    elif bolum is not None:
        qs = qs.filter(bolum=bolum)
    return qs.order_by("bolum__ad", "ad_soyad")


def kapsamdaki_personel(y, pk):
    p = Personel.objects.filter(pk=pk, aktif=True).select_related("bolum").first()
    if p is None or not y.goruntule or not y.kapsar(p):
        raise Http404("Personel bulunamadı.")
    return p


def degistirebilir_mi(y, donem):
    return y.yonetim or (y.bildir and donem.acik_mi)


def hucreleri_temizle(donem, ham):
    """Formdan gelen {"g-s": durum} sözlüğünü dönemin ızgarasına göre süzer."""
    temiz = {}
    for anahtar, durum in (ham or {}).items():
        if durum not in DURUMLAR:
            continue
        try:
            g, s = (int(x) for x in str(anahtar).split("-"))
        except ValueError:
            continue
        if 0 <= g < donem.gun_sayisi and 0 <= s < donem.saat_sayisi:
            temiz[f"{g}-{s}"] = durum
    return temiz


@transaction.atomic
def kaydet(user, y, donem, personel, hucreler, aciklama="", okunan_surum=None):
    """Bildirimi yazar. okunan_surum: formun açıldığı andaki sürüm (yeni kayıt için 0)."""
    if not y.kapsar(personel) or not degistirebilir_mi(y, donem):
        raise MazeretHatasi("Bu bildirimi değiştirme yetkiniz yok ya da dönem bildirime kapalı.")
    hucreler = hucreleri_temizle(donem, hucreler)
    aciklama = (aciklama or "").strip()
    b = DersMazeretBildirimi.objects.select_for_update().filter(donem=donem, personel=personel).first()
    if b is None:
        if okunan_surum not in (None, 0):
            raise MazeretHatasi("Bu bildirim bu sırada silinmiş; sayfayı yenileyin.")
        b = DersMazeretBildirimi.objects.create(donem=donem, personel=personel, hucreler=hucreler,
                                                aciklama=aciklama, bildiren=user)
    else:
        if okunan_surum is not None and okunan_surum != b.surum:
            raise MazeretHatasi("Bu bildirim siz düzenlerken başka bir kullanıcı tarafından değiştirildi. "
                                "Sayfayı yenileyip tekrar deneyin.")
        DersMazeretBildirimi.objects.filter(pk=b.pk).update(
            hucreler=hucreler, aciklama=aciklama, bildiren=user, surum=F("surum") + 1)
        b.refresh_from_db()
    DersMazeretGecmisi.objects.create(bildirim=b, kullanici=user, hucreler=hucreler, aciklama=aciklama)
    return b


def toplu_mazeretsiz(user, y, donem, personel_listesi):
    """Henüz bildirimi olmayan personel için "mazereti yok" (boş şablon) kaydeder."""
    var = set(DersMazeretBildirimi.objects.filter(donem=donem).values_list("personel_id", flat=True))
    yapilan = []
    for p in personel_listesi:
        if p.pk not in var:
            yapilan.append(kaydet(user, y, donem, p, {}, okunan_surum=0))
    return yapilan


# ---------------------------------------------------------------- Program Hazırlama'ya aktarım

def _ogretmene_yaz(okul, ogretmen, hucreler):
    from timetable.models import Availability

    saat_sayisi = okul.periods.count()
    Availability.objects.filter(school=okul, teacher=ogretmen).delete()
    satirlar = []
    for anahtar, durum in hucreler.items():
        g, s = (int(x) for x in anahtar.split("-"))
        if g < okul.days_per_week and s < saat_sayisi:
            satirlar.append(Availability(school=okul, teacher=ogretmen, day=g, period=s, state=durum))
    Availability.objects.bulk_create(satirlar)


@transaction.atomic
def programa_aktar(donem, bildirimler=None):
    """Bildirimleri dönemin bağlı olduğu programa yazar. Dönüş: (aktarılan, eşleşmeyen bildirimler)."""
    if donem.okul is None:
        return [], []
    if bildirimler is None:
        bildirimler = list(donem.bildirimler.select_related("personel"))
    eslesme = ogretmen_eslesmesi(donem.okul)
    aktarilan, eslesmeyen = [], []
    for b in bildirimler:
        t = eslesme.get(b.personel_id)
        if t is None:
            eslesmeyen.append(b)
        else:
            _ogretmene_yaz(donem.okul, t, b.hucreler)
            aktarilan.append(b)
    return aktarilan, eslesmeyen


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    """Açık dönemde bildirimi eksik personel (bölüm için "sizden bekleniyor")."""
    from django.urls import reverse

    from .models import DersMazeretDonemi

    y = yetki(request)
    if not y.bildir:
        return []
    gorevler = []
    for donem in DersMazeretDonemi.objects.filter(giris_acik=True):
        if not donem.acik_mi:
            continue
        kapsam = personeller(y)
        eksik = kapsam.exclude(ders_mazeretleri__donem=donem).count()
        if not eksik:
            continue
        son = f" · son gün {timezone.localtime(donem.son_bildirim):%d.%m.%Y %H:%M}" if donem.son_bildirim else ""
        gorevler.append({
            "renk": "bekliyor" if y.kapsam_bolum is None and y.yonetim else "eksik", "ikon": "calendar-x", "sayi": eksik,
            "ad": "Ders mazereti bildirilmemiş personel", "aciklama": f"{donem.ad}{son}",
            "url": f"{reverse('mazeret:ders')}?donem={donem.pk}&durum=yok",
        })
    return gorevler
