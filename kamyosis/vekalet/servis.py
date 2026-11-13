"""Vekâlet kuralları: yetki, görev önerisi, yoklamadaki izinlerden tarih önerisi, çakışma ve uyarılar."""

import datetime
from dataclasses import dataclass

from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, birim_bul, etkin_yetki
from personel.models import Bolum, Personel

from .models import Vekalet

BIRIM = "vekalet"
GUN = datetime.timedelta(days=1)

# yoklamadaki izin türü grubu → vekâlet nedeni
GRUP_NEDEN = {"saglik": Vekalet.RAPOR, "izin": Vekalet.IZIN, "aile": Vekalet.IZIN, "gorev": Vekalet.GOREV,
              "egitim": Vekalet.KURS}


@dataclass
class Yetkisi:
    goruntule: bool = False
    duzenle: bool = False
    kapsam_birim: object = None   # "kendi birimi" kapsamlı hesap (bölüm başkanı, şube müdürü, kısım amiri): birimi
    veren_idler: frozenset = None  # bu hesabın vekâlet veren olarak seçebileceği personel (None = herkes)
    bolum_gorevleri: dict = None   # {başkan: "<Bölüm> Bölüm Başkanı"} kapsamdaki bölümlerin başkanlığı
    varsayilan_veren: int = None   # formda hazır seçili veren: birimin başkanı / sorumlusu

    @property
    def tum_okul(self):
        return self.veren_idler is None

    def kapsar(self, vekalet):
        return self.veren_idler is None or vekalet.veren_id in self.veren_idler


def yetki(request):
    """Görüntüleme: bütün vekâletler. Düzenleme "tüm okul" kapsamında her vekâlet; "kendi birimi" kapsamında
    yalnız hesabın birimindeki (şube için alt kısımlar dahil) personelin ve o birimdeki bölümlerin başkanlarının
    verdiği vekâletler (başkan başka bölümün kadrosunda olsa da)."""
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye, kapsam = 0, None
    y = Yetkisi(goruntule=seviye >= GORUNTULEME, duzenle=seviye >= DUZENLEME)
    if y.duzenle and kapsam == Yetki.BOLUM:
        from yoklama.birim import Agac

        agac, u = Agac(), request.user
        b = agac.birimler.get(getattr(u, "teskilat_birimi_id", None)) or agac.bolumun(getattr(u, "bolum_id", None))
        if b is None:  # birimi atanmamış kapsamlı hesap hiçbir şey giremez
            y.duzenle = False
            return y
        idler = agac.alt_idler(b.pk)
        veren = set(Personel.objects.filter(aktif=True).filter(agac.kosul(idler)).values_list("pk", flat=True))
        y.bolum_gorevleri = {}
        for bolum in Bolum.objects.filter(baskan__isnull=False, aktif=True):
            bb = agac.bolumun(bolum.pk)
            if bb is not None and bb.pk in idler:
                veren.add(bolum.baskan_id)
                y.bolum_gorevleri[bolum.baskan_id] = f"{bolum.ad} Bölüm Başkanı"
        y.kapsam_birim, y.veren_idler = b, frozenset(veren)
        if b.bolum_id and b.bolum.baskan_id:
            y.varsayilan_veren = b.bolum.baskan_id
        else:
            from personel.kart import sorumlu_sec

            s = sorumlu_sec(list(Personel.objects.filter(aktif=True, teskilat_birimi=b).exclude(gorev_unvani="")))
            y.varsayilan_veren = s.pk if s else None
    return y


def personel_listesi():
    return Personel.objects.filter(aktif=True).select_related("unvan", "rutbe", "sinif", "bolum").order_by("ad_soyad")


def gorev_onerileri(y=None):
    """{personel_id: görev adı}: bölüm başkanı → "<Bölüm> Bölüm Başkanı", yoksa kartındaki görev unvanı. Birden çok
    bölümün başkanı olanda kendi birimi kapsamlı hesap için o birimin bölümü önerilir."""
    out = {p.pk: p.gorev_unvani for p in Personel.objects.filter(aktif=True).exclude(gorev_unvani="").only("gorev_unvani")}
    for b in Bolum.objects.filter(baskan__isnull=False, aktif=True).order_by("-ad"):
        out[b.baskan_id] = f"{b.ad} Bölüm Başkanı"
    if y is not None and y.bolum_gorevleri:
        out.update(y.bolum_gorevleri)
    return out


def gorev_listesi():
    """Görev kutusunun önerileri: bütün bölüm başkanlıkları ve kartlardaki görev unvanları."""
    adlar = {f"{b.ad} Bölüm Başkanı" for b in Bolum.objects.filter(aktif=True)}
    adlar |= set(Personel.objects.filter(aktif=True).exclude(gorev_unvani="").values_list("gorev_unvani", flat=True))
    return sorted(adlar)


def _gun_araligi(kayit):
    """Yoklama kaydının kapsadığı günler (bitiş gece yarısıysa önceki gün)."""
    bas, bit = timezone.localtime(kayit.baslangic), timezone.localtime(kayit.bitis)
    son = bit.date() - GUN if bit.time() == datetime.time(0) else bit.date()
    return bas.date(), max(son, bas.date())


def yaklasan_izinler(gun=90):
    """{personel_id: [{ad, bas, bit, neden}]}: bugünden itibaren yoklamadaki izin / rapor / görev kayıtları
    (formda vekâlet verenin tarihlerini tek tıkla doldurmak için)."""
    from yoklama.models import YoklamaKaydi

    simdi = timezone.now()
    out = {}
    qs = (YoklamaKaydi.objects.filter(bitis__gt=simdi, baslangic__lt=simdi + datetime.timedelta(days=gun),
                                      personel__aktif=True)
          .exclude(tur__mevcut_sayilir=True).select_related("tur").order_by("baslangic"))
    for k in qs:
        bas, bit = _gun_araligi(k)
        out.setdefault(k.personel_id, []).append({
            "ad": k.tur.ad, "bas": bas.isoformat(), "bit": bit.isoformat(),
            "neden": GRUP_NEDEN.get(k.tur.grup, Vekalet.DIGER),
            "metin": f"{bas:%d.%m}" + ("" if bas == bit else f"–{bit:%d.%m}")})
    return out


def surenler(bugun=None):
    """Sonlandırılmamış ve bitişi bugün ya da sonra (dönünceye kadar olanlar dahil) vekâletlerin koşulu."""
    bugun = bugun or timezone.localdate()
    return Q(sonlandirma__isnull=True) & (Q(bitis__isnull=True) | Q(bitis__gte=bugun))


def yururlukteler(bugun=None):
    bugun = bugun or timezone.localdate()
    return (Vekalet.objects.filter(surenler(bugun), baslangic__lte=bugun)
            .order_by(F("bitis").asc(nulls_last=True), "veren__ad_soyad"))


def _ortusen(qs, bas, bit):
    """bit None: dönünceye kadar (ucu açık)."""
    qs = qs.filter(sonlandirma__isnull=True).filter(Q(bitis__isnull=True) | Q(bitis__gte=bas))
    return qs if bit is None else qs.filter(baslangic__lte=bit)


def kontrol(v):
    """(hatalar, uyarılar). Hata kaydı engeller; uyarı onaylanırsa kaydedilir."""
    hatalar, uyarilar = [], []
    if v.veren_id and v.veren_id == v.vekil_id:
        hatalar.append("Personel kendisine vekâlet veremez.")
    if hatalar or not (v.baslangic and v.veren_id and v.vekil_id):
        return hatalar, uyarilar
    diger = Vekalet.objects.exclude(pk=v.pk)
    for c in _ortusen(diger.filter(veren_id=v.veren_id), v.baslangic, v.bitis):
        if c.gorev.strip().casefold() == v.gorev.strip().casefold():
            hatalar.append(f"{c.veren.ad_soyad} bu tarihlerde “{c.gorev}” görevi için zaten vekâlet vermiş "
                           f"(vekil: {c.vekil.ad_soyad}, {c.aralik_metni}).")
        else:
            uyarilar.append(f"{c.veren.ad_soyad} aynı tarihlerde “{c.gorev}” görevi için de vekâlet vermiş "
                            f"(vekil: {c.vekil.ad_soyad}, {c.aralik_metni}).")
    for c in _ortusen(diger.filter(veren_id=v.vekil_id), v.baslangic, v.bitis):
        uyarilar.append(f"Vekil {c.veren.ad_soyad} bu tarihlerde kendisi de “{c.gorev}” görevi için vekâlet vermiş "
                        f"(vekili: {c.vekil.ad_soyad}, {c.aralik_metni}).")
    from yoklama.servis import kayitlar

    tz = timezone.get_current_timezone()
    bas = timezone.make_aware(datetime.datetime.combine(v.baslangic, datetime.time(0)), tz)
    son = v.bitis or v.baslangic + datetime.timedelta(days=30)  # dönünceye kadar: ilk 30 güne bakılır
    bit = timezone.make_aware(datetime.datetime.combine(son + GUN, datetime.time(0)), tz)
    for k in kayitlar([v.vekil_id], bas, bit, yoklama=True):
        b, s = _gun_araligi(k)
        uyarilar.append(f"Vekil {k.personel.ad_soyad} personel yoklamasında {b:%d.%m}"
                        + ("" if b == s else f"–{s:%d.%m}") + f" tarihlerinde “{k.tur.ad}” görünüyor.")
    return hatalar, uyarilar


def gruplar(tumu=False, gecmis_gun=60):
    """Vekâletler sekmesi: (yürürlükte, başlayacak, geçmiş). Geçmiş son `gecmis_gun` gün (tumu=True: hepsi)."""
    bugun = timezone.localdate()
    qs = Vekalet.objects.select_related("veren__unvan", "veren__rutbe", "veren__sinif", "vekil__unvan",
                                        "vekil__rutbe", "vekil__sinif", "veren__bolum")
    yururlukte = list(qs.filter(surenler(bugun), baslangic__lte=bugun)
                      .order_by(F("bitis").asc(nulls_last=True), "veren__ad_soyad"))
    baslayacak = list(qs.filter(sonlandirma__isnull=True, baslangic__gt=bugun).order_by("baslangic", "veren__ad_soyad"))
    gecmis = qs.filter(Q(sonlandirma__isnull=False) | Q(bitis__lt=bugun)).order_by(F("bitis").desc(nulls_first=True),
                                                                                  "-sonlandirma", "-pk")
    if not tumu:
        sinir = bugun - datetime.timedelta(days=gecmis_gun)
        gecmis = gecmis.filter(Q(bitis__gte=sinir) | Q(bitis__isnull=True, sonlandirma__date__gte=sinir))
    return yururlukte, baslayacak, list(gecmis)


# ---------------------------------------------------------------- başka sayfalarda gösterim

def harita(bugun=None):
    """Bugün yürürlükte olan vekâletler: {personel_id: {"asil": [vekâlet verdiği], "vekil": [vekili olduğu]}}."""
    bugun = bugun or timezone.localdate()
    out = {}
    for v in yururlukteler(bugun).select_related("veren", "vekil"):
        out.setdefault(v.veren_id, {"asil": [], "vekil": []})["asil"].append(v)
        out.setdefault(v.vekil_id, {"asil": [], "vekil": []})["vekil"].append(v)
    return out


# ---------------------------------------------------------------- vekâleti girilmemiş yöneticiler

def yoneticiler():
    """Vekâlet bırakması beklenen personel: bölüm başkanları ve birim yöneticisi unvanlılar (müdür, amir, başkan …)."""
    from personel.kart import gorev_derecesi

    baskanlar = set(Bolum.objects.filter(baskan__isnull=False, aktif=True).values_list("baskan_id", flat=True))
    kisiler = Personel.objects.filter(aktif=True).filter(Q(pk__in=baskanlar) | ~Q(gorev_unvani=""))
    return [p for p in kisiler if p.pk in baskanlar or gorev_derecesi(p) <= 2]


def eksik_vekaletler(gun=7, bugun=None, y=None):
    """Önümüzdeki `gun` gün içinde yoklamada tam gün (en az 20 saat) izinli / raporlu / görevli görünen ve o tarihler
    için vekâleti girilmemiş yöneticiler: [{personel, gorev, tur, bas, bit, neden}] (başlangıca göre)."""
    from yoklama.servis import kayitlar

    bugun = bugun or timezone.localdate()
    kisiler = {p.pk: p for p in yoneticiler() if y is None or y.veren_idler is None or p.pk in y.veren_idler}
    if not kisiler:
        return []
    tz = timezone.get_current_timezone()
    bas = timezone.make_aware(datetime.datetime.combine(bugun, datetime.time(0)), tz)
    bit = bas + datetime.timedelta(days=gun + 1)
    gorevler = gorev_onerileri(y)
    vekaletler = list(Vekalet.objects.filter(surenler(bugun), veren_id__in=kisiler))
    out, gorulen = [], set()
    for k in kayitlar(list(kisiler), bas, bit, yoklama=True):
        if k.bitis - k.baslangic < datetime.timedelta(hours=20):
            continue
        b, s = _gun_araligi(k)
        b = max(b, bugun)
        if b > s or (k.personel_id, b) in gorulen:
            continue
        if any(v.veren_id == k.personel_id and v.baslangic <= s and (v.bitis is None or v.bitis >= b)
               for v in vekaletler):
            continue
        gorulen.add((k.personel_id, b))
        out.append({"personel": kisiler[k.personel_id], "gorev": gorevler.get(k.personel_id, ""), "tur": k.tur.ad,
                    "bas": b, "bit": s, "neden": GRUP_NEDEN.get(k.tur.grup, Vekalet.DIGER)})
    return sorted(out, key=lambda e: (e["bas"], e["personel"].ad_soyad))


# ---------------------------------------------------------------- ana sayfa

def panel_gorevleri(request):
    """Vekâlet girişi yapanlara "vekâleti girilmemiş yönetici", görüntüleyenlere "yürürlükteki vekâletler"."""
    from django.urls import reverse

    y = yetki(request)
    gorevler = []
    if y.duzenle:
        eksik = eksik_vekaletler(y=y)
        if eksik:
            ilk = eksik[0]
            gorevler.append({
                "renk": "eksik", "ikon": "person-exclamation", "sayi": len(eksik), "ad": "Vekâleti girilmemiş yönetici",
                "aciklama": f"{ilk['personel'].ad_soyad} · {ilk['tur']} {ilk['bas']:%d.%m}"
                            + (f" ve {len(eksik) - 1} kişi daha" if len(eksik) > 1 else ""),
                "url": reverse("vekalet:islemler")})
    if y.goruntule:
        bugun = timezone.localdate()
        aktif = list(yururlukteler(bugun).select_related("veren", "vekil"))
        if aktif:
            v = aktif[0]
            gorevler.append({
                "renk": "bekliyor", "ikon": "arrow-left-right", "sayi": len(aktif), "ad": "Yürürlükte vekâlet",
                "aciklama": f"{v.gorev}: {v.vekil.ad_soyad} ("
                            + ("dönünceye kadar" if v.acik_uclu else f"bitiş {v.bitis:%d.%m}") + ")"
                            + (f" · +{len(aktif) - 1} vekâlet" if len(aktif) > 1 else ""),
                "url": reverse("vekalet:liste")})
    return gorevler
