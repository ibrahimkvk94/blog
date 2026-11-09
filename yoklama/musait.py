"""Müsait personel sorgusu (İdari İşler): seçilen gün ve saat aralığında okulda olan, izinli olmayan, dersi ve sınav
görevi bulunmayan personel. Tören, toplantı, görevlendirme gibi işlere kimin ayrılabileceğini bulmak için.

Meşgul sayılanlar (her biri gerekçesiyle):
- İzin / rapor / görev: aralığa değen yoklama kaydı (bilgi amaçlı, "mevcut sayılır" türler hariç).
- Ders: o gün ders programında, ders saati aralığa değen dersi (devir kesinleşmişse devralan öğretmen).
- Sınav görevi: o gün aralığa değen oturumda gözetmen / salon amiri olarak yazılmış.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field

from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import GORUNTULEME, birim_bul, etkin_yetki
from personel.models import AKADEMIK_UNVANLAR, MEMUR_UNVANLARI, Personel

from .birim import BIRIMSIZ, Agac
from .servis import kayitlar

BIRIM = "musait-personel"
SINAV_OTURUM_EN_COK = 90  # dakika: oturumun süresi bilinmiyor; sonraki oturuma ya da en çok bu kadar sürdüğü varsayılır

KATEGORILER = [
    ("subay", "Subay"), ("astsubay", "Astsubay"), ("akademik", "Sivil öğretim elemanı"),
    ("memur", "Devlet memuru"), ("diger", "Diğer sivil"),
]
KATEGORI_ADI = dict(KATEGORILER)


def kategori(p):
    """Rütbesi olan askerî personel ("Asb." ile başlayan astsubay), rütbesizler unvana göre."""
    rutbe = str(p.rutbe or "").strip()
    if rutbe:
        return "astsubay" if rutbe.startswith("Asb") else "subay"
    unvan = str(p.unvan or "").strip()
    if unvan in AKADEMIK_UNVANLAR:
        return "akademik"
    if unvan in MEMUR_UNVANLARI:
        return "memur"
    return "diger"


# ---------------------------------------------------------------- yetki

@dataclass
class Yetkisi:
    goruntule: bool = False
    kapsam_birim: object = None  # None = tüm okul
    kapsam_idler: object = None
    agac: object = None


def yetki(request):
    y = Yetkisi(agac=Agac())
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule = seviye >= GORUNTULEME
    if y.goruntule and kapsam == Yetki.BOLUM:
        u = request.user
        b = y.agac.birimler.get(getattr(u, "teskilat_birimi_id", None)) or y.agac.bolumun(getattr(u, "bolum_id", None))
        if b is None:
            y.goruntule = False
        else:
            y.kapsam_birim, y.kapsam_idler = b, y.agac.alt_idler(b.pk)
    return y


# ---------------------------------------------------------------- sorgu

@dataclass
class Kisi:
    personel: object
    kategori: str
    birim: object
    nedenler: list = field(default_factory=list)  # [(tür, metin)] — boşsa müsait

    @property
    def kategori_adi(self):
        return KATEGORI_ADI[self.kategori]

    @property
    def musait(self):
        return not self.nedenler


def _an(tarih, saat):
    return timezone.make_aware(datetime.datetime.combine(tarih, saat), timezone.get_current_timezone())


def _ust_uste(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def _hm(t):
    return t.strftime("%H:%M")


def _ders_mesguliyetleri(tarih, bas, bit):
    """{personel_id: [metin]} — aralığa değen dersler."""
    from program.models import DersSaati
    from takip.servis import beklenen_dersler

    saatler = {}
    for ds in DersSaati.objects.exclude(baslangic=None).exclude(bitis=None):
        saatler[(ds.surum_id, ds.no)] = (ds.baslangic, ds.bitis)
    out = defaultdict(list)
    for s in beklenen_dersler(tarih, tarih):
        p = s.etkin_personel
        aralik = saatler.get((s.hucre.surum_id, s.hucre.saat))
        if p is None or aralik is None:
            continue
        if _ust_uste(bas, bit, *aralik):
            kisimlar = ", ".join(k.kod for k in s.hucre.haftalik_ders.kisimlar.all())
            out[p.pk].append(f"{s.hucre.saat}. saat ({_hm(aralik[0])}–{_hm(aralik[1])}) "
                             f"{s.hucre.haftalik_ders.ders.kod}{f' · {kisimlar}' if kisimlar else ''}")
    return out


def _sinav_mesguliyetleri(tarih, bas, bit):
    """{personel_id: [metin]} — aralığa değen sınav oturumlarındaki gözetmenlik / salon amirliği."""
    try:
        from dersprogrami_kopru.kunye import ogretmen_eslesmesi
        from sinav.models import ExamRoom
    except ImportError:  # Ders Programı modülü kurulu değil
        return {}
    out = defaultdict(list)
    eslesme = {}
    odalar = (ExamRoom.objects.filter(placement__date=tarih)
              .select_related("placement__exam__period__school", "placement__exam", "classroom")
              .prefetch_related("proctors"))
    for room in odalar:
        pl, e = room.placement, room.placement.exam
        period = e.period
        okul = period.school_id
        if okul not in eslesme:
            eslesme[okul] = {t.pk: pid for pid, t in ogretmen_eslesmesi(period.school).items()}
        oturumlar = period.session_times
        degiyor = False
        for k in range(max(1, e.duration)):
            i = pl.session + k
            if i >= len(oturumlar):
                break
            try:
                o_bas = datetime.datetime.strptime(oturumlar[i], "%H:%M").time()
            except ValueError:
                continue
            en_cok = (datetime.datetime.combine(tarih, o_bas) + datetime.timedelta(minutes=SINAV_OTURUM_EN_COK)).time()
            sonraki = None
            if i + 1 < len(oturumlar):
                try:
                    sonraki = datetime.datetime.strptime(oturumlar[i + 1], "%H:%M").time()
                except ValueError:
                    pass
            o_bit = min(en_cok, sonraki) if sonraki and sonraki > o_bas else en_cok
            if _ust_uste(bas, bit, o_bas, o_bit):
                degiyor = True
        if not degiyor:
            continue
        for t in room.proctors.all():
            pid = eslesme[okul].get(t.pk)
            if pid:
                rol = {"A": "salon amiri", "T": "taşıyıcı"}.get(room.role_of(t.pk), "gözetmen")
                out[pid].append(f"{oturumlar[pl.session]} oturumu {rol} · {e.title[:60]} ({room.classroom})")
    return out


def sorgula(y, tarih, bas_saat, bit_saat, kategoriler=None, birim=None, sinav=True):
    """[Kisi] — kapsamdaki aktif personel, meşguliyet gerekçeleriyle. Müsait olanların nedenler listesi boştur."""
    qs = Personel.objects.filter(aktif=True).select_related("bolum", "unvan", "rutbe", "sinif", "teskilat_birimi")
    idler = y.kapsam_idler
    if birim is not None:
        alt = y.agac.alt_idler(birim.pk) if birim.pk else {0}
        idler = alt if idler is None else (alt & idler)
    if idler is not None:
        qs = qs.filter(y.agac.kosul(idler))
    kisiler = [p for p in qs.order_by("ad_soyad") if not kategoriler or kategori(p) in kategoriler]

    bas_an, bit_an = _an(tarih, bas_saat), _an(tarih, bit_saat)
    izinler = defaultdict(list)
    for k in kayitlar([p.pk for p in kisiler], bas_an, bit_an, yoklama=True):
        if k.tam_gun:
            ne = f"{k.tur.ad} (tüm gün)"
        else:
            ne = f"{k.tur.ad} ({_hm(timezone.localtime(k.baslangic))}–{_hm(timezone.localtime(k.bitis))})"
        izinler[k.personel_id].append(ne)
    dersler = _ders_mesguliyetleri(tarih, bas_saat, bit_saat)
    sinavlar = _sinav_mesguliyetleri(tarih, bas_saat, bit_saat) if sinav else {}

    out = []
    for p in kisiler:
        k = Kisi(p, kategori(p), y.agac.birimler.get(y.agac.kisi_birimi(p)) or BIRIMSIZ)
        k.nedenler = ([("izin", n) for n in izinler.get(p.pk, [])] + [("ders", n) for n in dersler.get(p.pk, [])]
                      + [("sinav", n) for n in sinavlar.get(p.pk, [])])
        out.append(k)
    return out


def ozet(kisiler):
    """Sayılar: müsait / meşgul (gerekçe türlerine göre, bir kişi birden çok türde olabilir) ve kategorilere göre."""
    s = {"toplam": len(kisiler), "musait": 0, "izin": 0, "ders": 0, "sinav": 0}
    kat = {k: {"kod": k, "ad": a, "musait": 0, "toplam": 0} for k, a in KATEGORILER}
    for k in kisiler:
        kat[k.kategori]["toplam"] += 1
        if k.musait:
            s["musait"] += 1
            kat[k.kategori]["musait"] += 1
        for tur in {t for t, _ in k.nedenler}:
            s[tur] += 1
    s["kategoriler"] = [v for v in kat.values() if v["toplam"]]
    return s


def gruplu(kisiler, agac):
    """[(birim, [Kisi])] — teşkilat sırasıyla."""
    by = defaultdict(list)
    for k in kisiler:
        by[getattr(k.birim, "pk", 0)].append(k)
    out = [(b, by[b.pk]) for b, _ in agac.sirali() if by.get(b.pk)]
    if by.get(0):
        out.append((BIRIMSIZ, by[0]))
    return out
