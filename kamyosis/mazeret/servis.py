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
    tur_kod: str = "ders"           # ders mazereti: derse girenler; sınav mazereti: sınav görevi alabilenler

    def kapsar(self, personel):
        return self.kapsam_bolum is None or personel.bolum_id == self.kapsam_bolum.pk


def yetki(request, tur=None):
    tur = tur or TURLER["ders"]
    onbellek = request.__dict__.setdefault("_mazeret_yetkileri", {})
    if tur.kod in onbellek:
        return onbellek[tur.kod]
    y = MazeretYetkisi(tur_kod=tur.kod)
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
    kosul = {"sinav_gorevi_alabilir": True} if y.tur_kod == "sinav" else {"derse_girebilir": True}
    qs = Personel.objects.filter(aktif=True, **kosul).select_related("bolum", "unvan", "rutbe", "sinif")
    if y.tur_kod == "sinav":  # bölüm başkanları sınav görevi almaz, mazeret listesine girmez (09.11.2026)
        qs = qs.filter(baskani_oldugu_bolumler__isnull=True)
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


def sifirlanabilir_mi(y):
    """Sıfırlama yalnız yöneticide: mazeret biriminde Yönetim yetkisi, tüm okul kapsamı."""
    return y.yonetim and y.kapsam_bolum is None


@transaction.atomic
def sifirla(tur, donem, bolum=None, personel=None, teslimleri_kaldir=True):
    """Dönemin bildirimlerini siler (tümü / bölüm / kişi); aktarılmış işaretleri de hedeften (Program Hazırlama ya da
    Sınav Planlama) kaldırır. Dönüş: (silinen bildirim, geri alınan teslim)."""
    from .models import MazeretTeslimi

    qs = donem.bildirimler.select_related("personel")
    if personel is not None:
        qs = qs.filter(personel=personel)
    elif bolum is not None:
        qs = qs.filter(personel__bolum=bolum)
    bildirimler = list(qs)
    if bildirimler and hedef_adi(tur, donem):
        for b in bildirimler:  # boş işaretle aktar: hedefteki eski işaretler silinir (yoklama izinleri kalır)
            b.hucreler = {}
        aktar(tur, donem, bildirimler)
    silinen = len(bildirimler)
    qs.model.objects.filter(pk__in=[b.pk for b in bildirimler]).delete()
    teslim = 0
    if teslimleri_kaldir:
        t = MazeretTeslimi.objects.filter(tur=tur.kod, donem_id=donem.pk)
        if personel is not None:
            t = t.filter(bolum_id=personel.bolum_id) if personel.bolum_id else t.none()
        elif bolum is not None:
            t = t.filter(bolum=bolum)
        teslim = t.delete()[0]
    return silinen, teslim


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
    izinler = izin_isaretleri(donem, [b.personel_id for b in bildirimler])  # yoklamadaki izinler de kapatır
    for b in bildirimler:
        t = eslesme.get(b.personel_id)
        if t is None:
            eslesmeyen.append(b)
            continue
        hucreler = {**b.hucreler, **{k: YASAK for k in izinler.get(b.personel_id, {})}}
        kapali, kosullu = _isaretler(hucreler, saatler)
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
        kisiler = list(Personel.objects.filter(pk__in=eslesme, aktif=True))
        bildirimsiz_izin = izin_isaretleri(donem, [p.pk for p in kisiler if p.pk not in bildirimli])
        for p in kisiler:
            t = eslesme[p.pk]
            roller[str(t.pk)] = p.sinav_rolleri
            if p.pk not in bildirimli and donem.bildirimsize_gorev_yok:
                blocks[str(t.pk)] = tum_gunler
                soft.pop(str(t.pk), None)
            elif p.pk in bildirimsiz_izin:  # bildirimi yok ama izinli: izinli oturumlar kapalı
                kapali, _ = _isaretler({k: YASAK for k in bildirimsiz_izin[p.pk]}, saatler)
                blocks[str(t.pk)] = _oturum_listesi(kapali, n)
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


# ---------------------------------------------------------------- izinler (sınav): yoklamadaki kayıtlar oturumu kapatır

SINAV_OTURUM_EN_COK = 90  # dakika: oturumun bitişi bilinmiyor; sonraki oturuma ya da en çok bu kadar sürdüğü varsayılır


def oturum_araliklari(donem):
    """Sınav dönemi: {"YYYY-AA-GG SS:DD": (başlangıç, bitiş)} (saat dilimi bilgili). Ders döneminde boş."""
    import datetime

    if getattr(donem, "sinav_donemi_id", None) is None:
        return {}
    tz = timezone.get_current_timezone()
    oturumlar = []
    for o in donem.oturumlar():
        try:
            oturumlar.append((o, datetime.datetime.strptime(o, "%H:%M").time()))
        except ValueError:
            continue
    out = {}
    for t in donem.tarihler():
        for i, (o, bas) in enumerate(oturumlar):
            b = timezone.make_aware(datetime.datetime.combine(t, bas), tz)
            son = b + datetime.timedelta(minutes=SINAV_OTURUM_EN_COK)
            if i + 1 < len(oturumlar):
                sonraki = timezone.make_aware(datetime.datetime.combine(t, oturumlar[i + 1][1]), tz)
                if b < sonraki < son:
                    son = sonraki
            out[f"{t.isoformat()} {o}"] = (b, son)
    return out


def izin_isaretleri(donem, personel_idleri):
    """{personel_id: {hücre anahtarı: izin türü adı}} — sınav oturumuna değen yoklama kaydı (izin, rapor, görev …).
    Bilgi amaçlı türler (garnizon terk gibi, kişi mevcut sayılır) hariç."""
    from yoklama.servis import kayitlar

    araliklar = oturum_araliklari(donem)
    if not araliklar or not personel_idleri:
        return {}
    bas = min(a for a, _ in araliklar.values())
    bit = max(b for _, b in araliklar.values())
    out = defaultdict(dict)
    for k in kayitlar(list(personel_idleri), bas, bit, yoklama=True):
        for anahtar, (a, b) in araliklar.items():
            if k.baslangic < b and a < k.bitis:
                out[k.personel_id].setdefault(anahtar, k.tur.ad)
    return dict(out)


# ---------------------------------------------------------------- toplu tablo

@transaction.atomic
def toplu_kaydet(user, y, donem, veriler, surumler, aciklamalar=None):
    """Tablodan gelen {personel_id: hücreler}: değişen ya da bildirimi olmayan her satır kaydedilir (boş = mazereti yok).
    surumler: {personel_id: formun açıldığı andaki sürüm}; aciklamalar: {personel_id: satırın açıklaması} (gelmeyen
    satırın açıklaması korunur). Dönüş: (kaydedilen bildirimler, değişmeyen sayısı)."""
    aciklamalar = aciklamalar or {}
    if not degistirebilir_mi(y, donem):
        raise MazeretHatasi("Bu dönemde değişiklik yapma yetkiniz yok ya da dönem bildirime kapalı.")
    kisiler = {p.pk: p for p in Personel.objects.filter(pk__in=[int(k) for k in veriler], aktif=True)}
    mevcut = {b.personel_id: b for b in donem.bildirimler.filter(personel_id__in=kisiler)}
    kaydedilen, degismeyen = [], 0
    for pid_metin, hucreler in veriler.items():
        p = kisiler.get(int(pid_metin))
        if p is None or not y.kapsar(p):
            raise MazeretHatasi("Tabloda kapsamınız dışında personel var; sayfayı yenileyin.")
        temiz = hucreleri_temizle(donem, hucreler)
        b = mevcut.get(p.pk)
        eski = b.aciklama if b else ""
        aciklama = str(aciklamalar.get(pid_metin, eski) or "").strip()[:500]
        if b is not None and b.hucreler == temiz and b.aciklama == aciklama:
            degismeyen += 1
            continue
        kaydedilen.append(kaydet(user, y, donem, p, temiz, aciklama, int(surumler.get(pid_metin, 0) or 0)))
    return kaydedilen, degismeyen


# ---------------------------------------------------------------- bölüm teslimi

def bolum_durumlari(tur, donem, y, bolumler=None):
    """Bölüm başına: {bolum, toplam, bildirilen, eksik, teslim, sonradan} — teşkilat dışı (bölümsüz) personel hariç."""
    from .models import MazeretTeslimi

    tum = list(personeller(y))
    bildirimler = {b.personel_id: b for b in donem.bildirimler.all()}
    teslimler = {t.bolum_id: t for t in MazeretTeslimi.objects.filter(tur=tur.kod, donem_id=donem.pk)
                 .select_related("teslim_eden")}
    satir = {}
    for p in tum:
        if p.bolum_id is None or (bolumler is not None and p.bolum_id not in bolumler):
            continue
        s = satir.setdefault(p.bolum_id, {"bolum": p.bolum, "toplam": 0, "bildirilen": 0, "sonradan": 0,
                                          "teslim": teslimler.get(p.bolum_id)})
        s["toplam"] += 1
        b = bildirimler.get(p.pk)
        if b is not None:
            s["bildirilen"] += 1
            if s["teslim"] is not None and b.guncelleme > s["teslim"].zaman:
                s["sonradan"] += 1
    for s in satir.values():
        s["eksik"] = s["toplam"] - s["bildirilen"]
    return sorted(satir.values(), key=lambda s: s["bolum"].ad)


def teslim_et(user, y, tur, donem, bolum):
    from .models import MazeretTeslimi

    if not degistirebilir_mi(y, donem) or (y.kapsam_bolum is not None and y.kapsam_bolum.pk != bolum.pk):
        raise MazeretHatasi("Bu bölüm adına teslim yetkiniz yok ya da dönem bildirime kapalı.")
    durum = next((s for s in bolum_durumlari(tur, donem, y, {bolum.pk})), None)
    if durum is None:
        raise MazeretHatasi("Bu bölümde bildirim yapılacak personel yok.")
    if durum["eksik"]:
        raise MazeretHatasi(f"{durum['eksik']} personelin bildirimi eksik; önce tabloyu kaydedin.")
    t, _ = MazeretTeslimi.objects.update_or_create(tur=tur.kod, donem_id=donem.pk, bolum=bolum,
                                                    defaults={"teslim_eden": user})
    return t


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
                gorev = _teslim_gorevi(tur, donem, y, reverse)
                if gorev:
                    gorevler.append(gorev)
                continue
            son = f" · son gün {timezone.localtime(donem.son_bildirim):%d.%m.%Y %H:%M}" if donem.son_bildirim else ""
            gorevler.append({
                "renk": "bekliyor" if y.kapsam_bolum is None and y.yonetim else "eksik", "ikon": "calendar-x", "sayi": eksik,
                "ad": f"{tur.tekil} bildirilmemiş personel", "aciklama": f"{donem.ad}{son}",
                "url": f"{reverse(tur.url('liste'))}?donem={donem.pk}&durum=yok",
            })
    return gorevler


def _teslim_gorevi(tur, donem, y, reverse):
    """Bildirimler tamamken: bölüm hesabına "teslim edin", tüm okulu yönetene "teslim etmeyen bölüm" görevi."""
    url = f"{reverse(tur.url('liste'))}?donem={donem.pk}"
    durumlar = bolum_durumlari(tur, donem, y)
    if y.kapsam_bolum is not None:
        s = next((d for d in durumlar if d["bolum"].pk == y.kapsam_bolum.pk), None)
        if s and not s["eksik"] and s["teslim"] is None:
            return {"renk": "eksik", "ikon": "send-check", "sayi": None, "ad": f"{tur.tekil} bildirimini teslim edin",
                    "aciklama": f"{donem.ad} · bütün personel bildirildi", "url": url}
        return None
    if y.yonetim:
        n = sum(1 for d in durumlar if d["teslim"] is None)
        if n:
            return {"renk": "bekliyor", "ikon": "send-exclamation", "sayi": n, "ad": f"{tur.tekil} teslim etmeyen bölüm",
                    "aciklama": donem.ad, "url": url}
    return None
