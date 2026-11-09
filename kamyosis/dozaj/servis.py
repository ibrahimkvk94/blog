"""Dozajmatik hesabı: branş başına Güz/Bahar ders saati, öğretim elemanı mevcudu, ortalama ders yükü ve ihtiyaç.

Excel'deki 2026-2027 tablosunun kuralları:
- Ders saati: her ders için öğretim elemanı yükü (saat, 2. eleman girerse + uygulama saati) × o dönem dersi alan
  kısım sayısı; branş başına toplanır. Dersin branşı ders kodundan (KodBransi).
- Toplam = bölüm başkanı + subay + astsubay + sivil (+ yedek subay, branş ayarında dahilse).
- Ortalama = (saat − bölüm başkanı varsa başkan saati − karargâh/okul dışından gelenlerin saati)
             ÷ (toplam − bölüm başkanı varsa 1); bölünemezse saatin kendisi.
  Dışarıdan gelenlerin saati yalnız destek verdikleri dönemde düşülür.
- İhtiyaç (20 / 15 saat) = yukarı yuvarla(en yüklü dönemin saati − dışarıdan saat) ÷ eşik) − toplam, en az 0.
"""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from core.yetki import DUZENLEME, GORUNTULEME, birim_bul, etkin_yetki

from . import kurallar
from .models import Brans, BransAyari, Ders, KisiAyari, KodBransi, Program, Yil

BIRIM = "dozajmatik"
PROGRAM_BIRIM = "ogretim-programlari"  # Eğitim Bilimleri › Öğretim Programları (program sayfalarının kendi menüsü)
KADRO_SUTUNLARI = [KisiAyari.BB, KisiAyari.SB, KisiAyari.ASB, KisiAyari.SIVIL, KisiAyari.YEDEK]
KADRO_KISA = {KisiAyari.BB: "Böl.Bşk", KisiAyari.SB: "Sb.", KisiAyari.ASB: "Asb.", KisiAyari.SIVIL: "Sivil",
              KisiAyari.YEDEK: "Yedek Subay", KisiAyari.KH: "Kh.", KisiAyari.DIS: "Okul dışı",
              KisiAyari.HARIC: "Dahil değil"}


def _seviye(request, slug, gereken):
    u = request.user
    if not u.is_authenticated:
        return False
    if u.is_superuser:
        return True
    try:
        return etkin_yetki(request, birim_bul(request, slug))[0] >= gereken
    except Http404:
        return False


def duzenleyebilir(request):
    """Sayfanın açıldığı birimde (Dozajmatik ya da Öğretim Programları) düzenleme yetkisi."""
    birim = getattr(request, "birim", None)
    return _seviye(request, birim.slug if birim else BIRIM, DUZENLEME)


def gorebilir(request, slug):
    return _seviye(request, slug, GORUNTULEME)


def duzenleme_gerekli(request):
    if not duzenleyebilir(request):
        raise PermissionDenied


def yuvarla(x):
    """Excel gibi: yarım yukarı (13,5 → 14)."""
    if x is None:
        return None
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ortalama(saat, bb, toplam, dis, baskan_saati):
    payda = toplam - (1 if bb else 0)
    if payda <= 0:
        return float(saat)
    return (saat - (baskan_saati if bb else 0) - dis) / payda


def ihtiyac(guz, bahar, dis_guz, dis_bahar, toplam, esik):
    if not esik:
        return 0
    gereken = math.ceil(max(guz - dis_guz, bahar - dis_bahar, 0) / esik)
    return max(gereken - toplam, 0)


# ---------------------------------------------------------------- kişiler

@dataclass
class Kisi:
    personel: object
    brans: object  # Brans ya da None
    kadro: str
    oneri: object  # önerilen Brans ya da None
    secildi: bool  # branş elle seçildi mi
    ayar: object = None

    @property
    def kadro_kisa(self):
        return KADRO_KISA.get(self.kadro, self.kadro)


def kisiler(yil, branslar=None):
    """Aktif personelin o yılki branşı ve kadrosu (elle seçilen ya da karttan önerilen)."""
    from personel.models import Bolum, Personel

    branslar = branslar or {b.ad: b for b in Brans.objects.all()}
    ayarlar = {a.personel_id: a for a in KisiAyari.objects.filter(yil=yil).select_related("brans")}
    baskanlar = set(Bolum.objects.filter(aktif=True, baskan__isnull=False).values_list("baskan_id", flat=True))
    out = []
    for p in Personel.objects.filter(aktif=True).select_related("rutbe", "sinif", "unvan", "bolum"):
        a = ayarlar.get(p.pk)
        oneri = branslar.get(kurallar.brans_oneri_adi(p) or "")
        if a and a.brans_yok:
            brans, secildi = None, True
        elif a and a.brans_id:
            brans, secildi = a.brans, True
        else:
            brans, secildi = oneri, False
        kadro = (a.kadro if a and a.kadro else kurallar.otomatik_kadro(p, baskanlar))
        out.append(Kisi(p, brans, kadro, oneri, secildi, a))
    return out


# ---------------------------------------------------------------- hesap

@dataclass
class Satir:
    brans: object
    guz: int = 0
    bahar: int = 0
    kadro: Counter = field(default_factory=Counter)
    ayar: object = None
    dersler: list = field(default_factory=list)
    kisiler: list = field(default_factory=list)

    def __post_init__(self):
        self.ayar = self.ayar or BransAyari(brans=self.brans)

    # kadro sütunları
    bb = property(lambda s: s.kadro[KisiAyari.BB])
    sb = property(lambda s: s.kadro[KisiAyari.SB])
    asb = property(lambda s: s.kadro[KisiAyari.ASB])
    sivil = property(lambda s: s.kadro[KisiAyari.SIVIL])
    yedek = property(lambda s: s.kadro[KisiAyari.YEDEK])

    @property
    def toplam(self):
        return self.bb + self.sb + self.asb + self.sivil + (self.yedek if self.ayar.atgm_dahil else 0)

    @property
    def kh(self):
        return self.kadro[KisiAyari.KH] + self.ayar.kh_sayi

    @property
    def dis(self):
        return self.kadro[KisiAyari.DIS] + self.ayar.dis_sayi

    @property
    def dis_guz(self):
        return self.ayar.dis_saat if self.ayar.destek in (BransAyari.DESTEK_GUZ, BransAyari.DESTEK_IKISI) else 0

    @property
    def dis_bahar(self):
        return self.ayar.dis_saat if self.ayar.destek in (BransAyari.DESTEK_BAHAR, BransAyari.DESTEK_IKISI) else 0


class Hesap:
    def __init__(self, yil):
        self.yil = yil
        self.branslar = list(Brans.objects.all())
        by_ad = {b.ad: b for b in self.branslar}
        ayarlar = {a.brans_id: a for a in BransAyari.objects.filter(yil=yil)}
        self.satir = {b.pk: Satir(b, ayar=ayarlar.get(b.pk)) for b in self.branslar}
        kod_brans = {k.kod: k.brans_id for k in KodBransi.objects.filter(yil=yil)}
        self.programlar = list(Program.objects.filter(yil=yil))
        self.kodsuz = defaultdict(list)  # kod → [Ders]
        for d in Ders.objects.filter(program__yil=yil).select_related("program"):
            g, b = d.kisimlar()
            bid = kod_brans.get(d.kod)
            if bid is None:
                self.kodsuz[d.kod].append(d)
                continue
            s = self.satir[bid]
            s.guz += d.yuk * g
            s.bahar += d.yuk * b
            s.dersler.append({"ders": d, "guz_kisim": g, "bahar_kisim": b, "guz": d.yuk * g, "bahar": d.yuk * b})
        self.kisiler = kisiler(yil, by_ad)
        self.branssiz = []
        for k in self.kisiler:
            if k.brans is None:
                if k.personel.derse_girebilir and not (k.ayar and k.ayar.brans_yok):
                    self.branssiz.append(k)
                continue
            s = self.satir[k.brans.pk]
            s.kisiler.append(k)
            if k.kadro != KisiAyari.HARIC:
                s.kadro[k.kadro] += 1

    # ---------------------------------------------------------------- tablo
    def satirlar(self):
        """Tablodaki branşlar (hesaba katılanlar), sırayla, ortalama ve ihtiyaçla."""
        y = self.yil
        out = []
        for b in self.branslar:
            if not b.hesapta:
                continue
            s = self.satir[b.pk]
            og = ortalama(s.guz, s.bb, s.toplam, s.dis_guz, y.baskan_saati)
            ob = ortalama(s.bahar, s.bb, s.toplam, s.dis_bahar, y.baskan_saati)
            s.ort_guz, s.ort_bahar = og, ob
            s.ort_guz_g, s.ort_bahar_g = yuvarla(og), yuvarla(ob)
            s.guz_uyari = og >= y.uyari_esigi
            s.bahar_uyari = ob >= y.uyari_esigi
            s.ihtiyac1 = ihtiyac(s.guz, s.bahar, s.dis_guz, s.dis_bahar, s.toplam, y.ihtiyac_saat1)
            s.ihtiyac2 = ihtiyac(s.guz, s.bahar, s.dis_guz, s.dis_bahar, s.toplam, y.ihtiyac_saat2)
            out.append(s)
        # grup başlıkları (Excel'deki birleştirilmiş BÖLÜM hücresi)
        for i, s in enumerate(out):
            ilk = i == 0 or out[i - 1].brans.grup != s.brans.grup
            s.grup_ilk = ilk
            if ilk:
                n = 1
                while i + n < len(out) and out[i + n].brans.grup == s.brans.grup:
                    n += 1
                s.grup_satir = n
        return out

    def toplamlar(self, satirlar):
        t = {k: sum(getattr(s, k) for s in satirlar)
             for k in ("guz", "bahar", "bb", "sb", "asb", "sivil", "yedek", "toplam", "kh", "dis", "ihtiyac1",
                       "ihtiyac2")}
        t["kadro"] = t["bb"] + t["sb"] + t["asb"] + t["sivil"] + t["yedek"]
        t["genel"] = t["toplam"] + t["kh"] + t["dis"]
        # Excel: (Güz + Bahar) / 2 ÷ öğretim elemanı sayısı
        t["ortalama"] = (t["guz"] + t["bahar"]) / 2 / t["toplam"] if t["toplam"] else None
        return t

    def hesap_disi(self):
        """Tabloya girmeyen branşların saatleri (ör. Afet)."""
        return [self.satir[b.pk] for b in self.branslar if not b.hesapta and (self.satir[b.pk].guz or
                                                                               self.satir[b.pk].bahar)]

    def kisim_toplami(self):
        """(1. sınıf, 2. sınıf, hazırlık) kısım toplamları."""
        ana = [p for p in self.programlar if not p.hazirlik]
        return (sum(p.kisim1 for p in ana), sum(p.kisim2 for p in ana),
                sum(p.kisim1 + p.kisim2 for p in self.programlar if p.hazirlik))


# ---------------------------------------------------------------- yıl

def yil_sec(request):
    """?yil=<pk> (oturuma yazılır) → oturumdaki → varsayılan → en yenisi. Hiç yıl yoksa None."""
    pk = request.GET.get("yil")
    if pk and pk.isdigit():
        y = Yil.objects.filter(pk=pk).first()
        if y:
            request.session["dozaj_yil"] = y.pk
            return y
    y = Yil.objects.filter(pk=request.session.get("dozaj_yil") or 0).first()
    return y or Yil.objects.filter(varsayilan=True).first() or Yil.objects.first()


def kod_branslarini_tamamla(yil):
    """Programlardaki, branşı henüz belirlenmemiş ders kodlarına kurallardan varsayılan branş yazar."""
    var = set(KodBransi.objects.filter(yil=yil).values_list("kod", flat=True))
    by_ad = {b.ad: b for b in Brans.objects.all()}
    yeni = []
    for kod in set(Ders.objects.filter(program__yil=yil).values_list("kod", flat=True)) - var:
        b = by_ad.get(kurallar.kod_bransi(kod) or "")
        if b:
            yeni.append(KodBransi(yil=yil, kod=kod, brans=b))
    KodBransi.objects.bulk_create(yeni)
    return len(yeni)


@transaction.atomic
def yil_kopyala(kaynak, ad):
    """Kaynak yılın programları, dersleri, kod branşları, branş ve kişi ayarlarıyla yeni yıl."""
    y = Yil.objects.create(ad=ad, uyari_esigi=kaynak.uyari_esigi, ihtiyac_saat1=kaynak.ihtiyac_saat1,
                           ihtiyac_saat2=kaynak.ihtiyac_saat2, baskan_saati=kaynak.baskan_saati)
    for p in kaynak.programlar.prefetch_related("dersler"):
        dersler = list(p.dersler.all())
        p.pk, p.yil = None, y
        p.save()
        for d in dersler:
            d.pk, d.program = None, p
        Ders.objects.bulk_create(dersler)
    KodBransi.objects.bulk_create([KodBransi(yil=y, kod=k.kod, brans_id=k.brans_id) for k in kaynak.kod_branslari.all()])
    BransAyari.objects.bulk_create([BransAyari(yil=y, brans_id=a.brans_id, atgm_dahil=a.atgm_dahil, kh_sayi=a.kh_sayi,
                                               dis_sayi=a.dis_sayi, dis_saat=a.dis_saat, destek=a.destek)
                                    for a in kaynak.brans_ayarlari.all()])
    KisiAyari.objects.bulk_create([KisiAyari(yil=y, personel_id=a.personel_id, brans_id=a.brans_id,
                                             brans_yok=a.brans_yok, kadro=a.kadro)
                                   for a in kaynak.kisi_ayarlari.all()])
    return y
