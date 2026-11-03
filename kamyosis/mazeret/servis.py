"""Ders ve sınav mazereti iş kuralları.

- Bölüm kapsamlı kullanıcı yalnızca kendi bölümünün personelini görür ve bildirir.
- Düzenleme yetkisi bildirim yapar; dönem kapalıysa ya da son bildirim zamanı geçtiyse
  yalnızca yönetim yetkisi değiştirebilir.
- Kaydetme iyimser kilitle yapılır: başkası araya girdiyse kayıt reddedilir.
- Ders dönemi bir Program Hazırlama programına bağlıysa her kayıt o programdaki öğretmenin
  müsaitliğini değiştirir (öğretmen ad soyadla eşleştirilir; T.C. kimlik no kullanılmaz).
- Sınav dönemi Sınav Planlama'daki bir sınav dönemine bağlıdır: her kayıt o dönemde öğretmenin gözetmenlik
  müsaitliğine yazılır (✗ → kapalı oturum, ? → mümkünse görev verilmesin). Dönemin tamamı aktarılırken
  (elle ya da sınav programı oluşturulmadan hemen önce) bildirimi olmayan personelin tüm oturumları kapatılır
  (dönem ayarı, PPYS kuralı) ve personelin sınav görev rolleri döneme işlenir.
"""

from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.db.models import F
from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from dersprogrami_kopru.kunye import ogretmen_eslesmesi
from personel.models import Personel

from .models import DURUMLAR, YASAK, DersMazeretDonemi, SinavMazeretDonemi

BIRIM_DERS = "ders-mazeretleri"
BIRIM_SINAV = "sinav-mazeretleri"


@dataclass(frozen=True)
class Tur:
    """Mazeret türü: ekranlar ve kurallar iki türde aynıdır, yalnızca ızgara ve aktarım hedefi değişir."""

    kod: str
    birim: str
    baslik: str
    tekil: str
    birim_adi: str          # ızgara hücresinin adı: saat / oturum
    yasak_metni: str        # ✗ işaretinin anlamı
    url_on_ek: str          # url adları: "" → mazeret:bildirim, "sinav_" → mazeret:sinav_bildirim
    iliski: str             # Personel üzerindeki ters ilişki adı
    model_adi: str          # yönetim paneli için
    donem_modeli: type

    def url(self, ad):
        """liste → mazeret:ders / mazeret:sinav; diğerleri → mazeret:bildirim / mazeret:sinav_bildirim …"""
        return f"mazeret:{self.kod}" if ad == "liste" else f"mazeret:{self.url_on_ek}{ad}"


TURLER = {
    "ders": Tur("ders", BIRIM_DERS, "Ders mazeretleri", "Ders mazereti", "saat", "ders verilemez", "", "ders_mazeretleri",
                "dersmazeretdonemi", DersMazeretDonemi),
    "sinav": Tur("sinav", BIRIM_SINAV, "Sınav mazeretleri", "Sınav mazereti", "oturum", "görev verilemez", "sinav_", "sinav_mazeretleri",
                 "sinavmazeretdonemi", SinavMazeretDonemi),
}


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


def yetki(request, tur=None):
    tur = tur or TURLER["ders"]
    onbellek = request.__dict__.setdefault("_mazeret_yetkileri", {})
    if tur.kod in onbellek:
        return onbellek[tur.kod]
    y = MazeretYetkisi()
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, tur.birim))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule, y.bildir, y.yonetim = seviye >= GORUNTULEME, seviye >= DUZENLEME, seviye >= YONETIM
    if kapsam == Yetki.BOLUM:
        y.kapsam_bolum = request.user.bolum
        if y.kapsam_bolum is None:  # bölümü atanmamış bölüm kullanıcısı hiçbir şeyi kapsamaz
            y.goruntule = y.bildir = y.yonetim = False
    onbellek[tur.kod] = y
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
    """Formdan gelen {anahtar: durum} sözlüğünü dönemin ızgarasına göre süzer."""
    gecerli = donem.anahtarlar()
    return {str(k): d for k, d in (ham or {}).items() if d in DURUMLAR and str(k) in gecerli}


@transaction.atomic
def kaydet(user, y, donem, personel, hucreler, aciklama="", okunan_surum=None):
    """Bildirimi yazar. okunan_surum: formun açıldığı andaki sürüm (yeni kayıt için 0)."""
    if not y.kapsar(personel) or not degistirebilir_mi(y, donem):
        raise MazeretHatasi("Bu bildirimi değiştirme yetkiniz yok ya da dönem bildirime kapalı.")
    Bildirim = donem.bildirimler.model
    hucreler = hucreleri_temizle(donem, hucreler)
    aciklama = (aciklama or "").strip()
    b = Bildirim.objects.select_for_update().filter(donem=donem, personel=personel).first()
    if b is None:
        if okunan_surum not in (None, 0):
            raise MazeretHatasi("Bu bildirim bu sırada silinmiş; sayfayı yenileyin.")
        b = Bildirim.objects.create(donem=donem, personel=personel, hucreler=hucreler, aciklama=aciklama, bildiren=user)
    else:
        if okunan_surum is not None and okunan_surum != b.surum:
            raise MazeretHatasi("Bu bildirim siz düzenlerken başka bir kullanıcı tarafından değiştirildi. "
                                "Sayfayı yenileyip tekrar deneyin.")
        Bildirim.objects.filter(pk=b.pk).update(hucreler=hucreler, aciklama=aciklama, bildiren=user, surum=F("surum") + 1)
        b.refresh_from_db()
    b.gecmis.create(kullanici=user, hucreler=hucreler, aciklama=aciklama)
    return b


def toplu_mazeretsiz(user, y, donem, personel_listesi):
    """Henüz bildirimi olmayan personel için "mazereti yok" (boş şablon) kaydeder."""
    var = set(donem.bildirimler.values_list("personel_id", flat=True))
    yapilan = []
    for p in personel_listesi:
        if p.pk not in var:
            yapilan.append(kaydet(user, y, donem, p, {}, okunan_surum=0))
    return yapilan


def gecersiz_isaretler(donem):
    """Sınav dönemi: oturum saati ya da günü sonradan değiştiği için ızgarada artık olmayan işaret sayısı."""
    gecerli = donem.anahtarlar()
    return sum(1 for b in donem.bildirimler.all() for k in b.hucreler if k not in gecerli)


# ---------------------------------------------------------------- Program Hazırlama'ya aktarım (ders)

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


# ---------------------------------------------------------------- Sınav Planlama'ya aktarım (sınav)

def _oturum_listesi(gunler, oturum_sayisi):
    """{tarih: {oturum sırası}} → ["2026-11-10", "2026-11-11#0", ...] (tüm oturumları seçili gün tek kayıt)."""
    out = []
    for tarih, sec in sorted(gunler.items()):
        out += [tarih] if len(sec) >= oturum_sayisi else [f"{tarih}#{i}" for i in sorted(sec)]
    return out


def _isaretler(hucreler, saatler):
    """Bildirim hücreleri → ({tarih: {oturum}} kapalı, {tarih: {oturum}} mümkünse verilmesin)."""
    kapali, kosullu = defaultdict(set), defaultdict(set)
    for anahtar, durum in hucreler.items():
        tarih, _, saat = anahtar.partition(" ")
        if saat in saatler and durum in DURUMLAR:
            (kapali if durum == YASAK else kosullu)[tarih].add(saatler[saat])
    return kapali, kosullu


@transaction.atomic
def sinava_aktar(donem, bildirimler=None):
    """Bildirimleri bağlı sınav döneminin gözetmen müsaitliğine yazar. bildirimler verilmezse dönemin tamamı aktarılır:
    bildirimsiz personel (dönem ayarına göre) tüm oturumlarda kapalı sayılır, görev rolleri ve rol kuralı işlenir.
    Dönüş: (aktarılan, eşleşmeyen bildirimler)."""
    from sinav.models import DEFAULT_ROLES, ExamPeriod

    if donem.sinav_donemi_id is None:
        return [], []
    period = ExamPeriod.objects.select_for_update().select_related("school").get(pk=donem.sinav_donemi_id)
    tumu = bildirimler is None
    if tumu:
        bildirimler = list(donem.bildirimler.select_related("personel"))
    eslesme = ogretmen_eslesmesi(period.school)
    saatler = {o: i for i, o in enumerate(period.session_times)}
    n = len(saatler)
    blocks, soft = dict(period.proctor_blocks or {}), dict(period.proctor_soft or {})
    aktarilan, eslesmeyen = [], []
    for b in bildirimler:
        t = eslesme.get(b.personel_id)
        if t is None:
            eslesmeyen.append(b)
            continue
        kapali, kosullu = _isaretler(b.hucreler, saatler)
        for hedef, gunler in ((blocks, kapali), (soft, kosullu)):
            liste = _oturum_listesi(gunler, n)
            if liste:
                hedef[str(t.pk)] = liste
            else:
                hedef.pop(str(t.pk), None)
        aktarilan.append(b)
    alanlar = ["proctor_blocks", "proctor_soft"]
    if tumu:
        bildirimli = {b.personel_id for b in bildirimler}
        tum_gunler = [d.isoformat() for d in period.dates()]
        roller = dict(period.proctor_roles or {})
        for p in Personel.objects.filter(pk__in=eslesme, aktif=True):
            t = eslesme[p.pk]
            roller[str(t.pk)] = p.sinav_rolleri
            if p.pk not in bildirimli and donem.bildirimsize_gorev_yok:
                blocks[str(t.pk)] = tum_gunler
                soft.pop(str(t.pk), None)
        period.proctor_roles = {k: v for k, v in roller.items() if v != DEFAULT_ROLES}
        period.duty_roles = True
        alanlar += ["proctor_roles", "duty_roles"]
    period.proctor_blocks, period.proctor_soft = blocks, soft
    period.save(update_fields=alanlar)
    return aktarilan, eslesmeyen


def sinav_donemini_esitle(period_id):
    """Sınav programı oluşturulmadan önce: bağlı mazeret döneminin tamamını aktarır (yoksa bir şey yapmaz)."""
    donem = SinavMazeretDonemi.objects.filter(sinav_donemi_id=period_id).first()
    if donem is not None:
        sinava_aktar(donem)


def aktar(tur, donem, bildirimler=None):
    return (sinava_aktar if tur.kod == "sinav" else programa_aktar)(donem, bildirimler)


def hedef_adi(tur, donem):
    """Aktarımın yazıldığı yer (iletiler için); bağlı değilse None."""
    if tur.kod == "sinav":
        return f"Sınav Planlama'da “{donem.sinav_donemi}” dönemindeki gözetmen müsaitliği" if donem.sinav_donemi_id else None
    return f"Program Hazırlama'da “{donem.okul}” programındaki müsaitlik" if donem.okul_id else None


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    """Açık dönemde bildirimi eksik personel (bölüm için "sizden bekleniyor")."""
    from django.urls import reverse

    gorevler = []
    for tur in TURLER.values():
        y = yetki(request, tur)
        if not y.bildir:
            continue
        for donem in tur.donem_modeli.objects.filter(giris_acik=True):
            if not donem.acik_mi:
                continue
            eksik = personeller(y).exclude(**{f"{tur.iliski}__donem": donem}).count()
            if not eksik:
                continue
            son = f" · son gün {timezone.localtime(donem.son_bildirim):%d.%m.%Y %H:%M}" if donem.son_bildirim else ""
            gorevler.append({
                "renk": "bekliyor" if y.kapsam_bolum is None and y.yonetim else "eksik", "ikon": "calendar-x", "sayi": eksik,
                "ad": f"{tur.tekil} bildirilmemiş personel", "aciklama": f"{donem.ad}{son}",
                "url": f"{reverse(tur.url('liste'))}?donem={donem.pk}&durum=yok",
            })
    return gorevler
