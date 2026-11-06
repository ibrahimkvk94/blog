"""Nöbet dağıtımı ve adalet (puantaj) hesabı.

Dağıtım sırası:
1. Kilitli (elle yapılmış) atamalar korunur.
2. Sabit görevliler kendi görevlerine yazılır ("sadece sabit" görevlere başkası yazılmaz).
3. Yatılı görevler birlikte: yıl içinde en az yatılı tutanlar seçilir; ayar açıksa her kişi
   daha az tuttuğu yatılı türe (ör. orduevi / bilgisayar) yazılır.
4. Diğer görevler, en az adayı olandan başlayarak; aday sırası:
   (yatılıysa yatılı sayısı, geçen ay aynı görev mi, toplam puan, bu görevi tutma sayısı, sabit kura)
5. Kontenjanı boş ("kalan herkes") görevler en son, kalanları eşit bölüşür.
Kontenjan o ay için tanımlı aylık kontenjan, yoksa görevin genel kontenjanıdır.
Kısıtlaması (izin, kurs, tayin, YDGG, "bu ay yazılamaz" ...) o ayla kesişen personel dağıtıma girmez.
Kura sabittir: aynı veriyle aynı ay her zaman aynı sonucu verir.
Geçmiş = nöbet yılının bu aydan önceki ayları (taslaklar dahil).
"""

import hashlib
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from personel.models import Personel

from .models import AYLAR, NobetAtamasi, NobetAyari, NobetDonemi, NobetGorevi, NobetKisitlamasi, NobetKontenjani


class NobetHatasi(Exception):
    pass


# ---------------------------------------------------------------- uygunluk

def ay_araligi(yil, ay):
    ilk = date(yil, ay, 1)
    return ilk, date(yil, ay, monthrange(yil, ay)[1])


def ay_kisitlamalari(yil, ay):
    """Bu ayla kesişen kısıtlamalar: {personel_id: NobetKisitlamasi} (birden fazlaysa ilki)."""
    ilk, son = ay_araligi(yil, ay)
    sonuc = {}
    for k in NobetKisitlamasi.objects.filter(baslangic__lte=son).filter(Q(bitis=None) | Q(bitis__gte=ilk)).order_by("baslangic"):
        sonuc.setdefault(k.personel_id, k)
    return sonuc


def uygun_personel(donem):
    """Bu ay nöbet tutabilecek personel: aktif, rütbesi belli, muaf/tutamaz değil (süresi dolan muafiyet hariç),
    o ayla kesişen bir kısıtlaması (izin, kurs, tayin, YDGG ...) yok."""
    ilk = donem.ilk_gun
    engelli = ay_kisitlamalari(donem.yil, donem.ay)
    return (
        Personel.objects.filter(aktif=True)
        .exclude(rutbe=None)
        .exclude(pk__in=engelli)
        .filter(Q(nobet_durumu=Personel.NOBET_TUTAR)
                | Q(nobet_durumu=Personel.NOBET_MUAF, nobet_muafiyet_bitis__lt=ilk))
        .select_related("rutbe", "sinif", "unvan", "bolum")
    )


def muaf_personel(donem):
    """Bu ay nöbete giremeyenler; her birinin `muaf_nedeni` alanı doldurulur."""
    ilk = donem.ilk_gun
    engelli = ay_kisitlamalari(donem.yil, donem.ay)
    kisiler = (
        Personel.objects.filter(aktif=True)
        .filter(Q(nobet_durumu=Personel.NOBET_TUTAMAZ)
                | (Q(nobet_durumu=Personel.NOBET_MUAF) & (Q(nobet_muafiyet_bitis=None) | Q(nobet_muafiyet_bitis__gte=ilk)))
                | Q(pk__in=engelli))
        .select_related("rutbe", "sinif", "unvan")
    )
    sonuc = sorted(kisiler, key=lambda p: p.ad_soyad)
    for p in sonuc:
        k = engelli.get(p.pk)
        p.muaf_nedeni = (k.aciklama or k.get_tur_display()) if k else (p.nobet_muafiyet_nedeni or p.get_nobet_durumu_display())
    return sonuc


# ---------------------------------------------------------------- geçmiş (puantaj)

@dataclass
class Gecmis:
    yatili: int = 0
    puan: Decimal = Decimal(0)
    gorevler: Counter = field(default_factory=Counter)
    aylar: dict = field(default_factory=dict)  # sira_no -> NobetAtamasi


def nobet_yili_donemleri(yil_basi, ay_basi):
    """Nöbet yılının 12 ayının (yıl, ay) listesi."""
    sonuc = []
    y, a = yil_basi, ay_basi
    for _ in range(12):
        sonuc.append((y, a))
        a += 1
        if a > 12:
            y, a = y + 1, 1
    return sonuc


def gecmis(donem, sadece_kesin=False, dahil=False):
    """Nöbet yılının başından bu aya kadar (dahil=True ise bu ay da) kişi bazında geçmiş.

    Taslak aylar da sayılır: yıllık planda sonraki aylar önceki taslaklara göre dengelenir.
    """
    ayar = NobetAyari.al()
    yb, ab = donem.nobet_yili(ayar.yil_baslangic_ayi)
    aylar = nobet_yili_donemleri(yb, ab)
    secili = [ya for ya in aylar if (ya[0] * 12 + ya[1] - 1) < donem.sira_no or (dahil and ya == (donem.yil, donem.ay))]
    q = Q(pk__in=[])
    for y, a in secili:
        q |= Q(donem__yil=y, donem__ay=a)
    atamalar = NobetAtamasi.objects.filter(q).select_related("gorev", "donem")
    if sadece_kesin:
        atamalar = atamalar.filter(Q(donem__durum=NobetDonemi.KESIN) | Q(donem=donem))
    sonuc = defaultdict(Gecmis)
    for at in atamalar:
        g = sonuc[at.personel_id]
        g.puan += at.gorev.puan
        g.yatili += 1 if at.gorev.yatili else 0
        g.gorevler[at.gorev_id] += 1
        g.aylar[at.donem.sira_no] = at
    return sonuc


def onceki_ay_gorevleri(donem):
    y, a = (donem.yil, donem.ay - 1) if donem.ay > 1 else (donem.yil - 1, 12)
    return dict(NobetAtamasi.objects.filter(donem__yil=y, donem__ay=a).values_list("personel_id", "gorev_id"))


def _kura(personel_id, donem, gorev_id):
    h = hashlib.sha256(f"{personel_id}-{donem.yil}-{donem.ay}-{gorev_id}".encode()).hexdigest()
    return int(h[:8], 16)


# ---------------------------------------------------------------- dağıtım

@dataclass
class DagitimRaporu:
    atanan: int = 0
    eksik: list = field(default_factory=list)       # (görev, eksik sayısı)
    bosta: list = field(default_factory=list)       # uygun ama hiçbir göreve sığmayan personel
    rutbesiz: int = 0


@transaction.atomic
def dagit(donem):
    if donem.durum == NobetDonemi.KESIN:
        raise NobetHatasi("Kesinleşmiş ay yeniden dağıtılamaz. Önce taslağa alın.")
    ayar = NobetAyari.al()
    donem.atamalar.filter(kilitli=False).delete()
    kilitli = list(donem.atamalar.select_related("gorev"))
    dolu_kisi = {a.personel_id for a in kilitli}
    gorev_dolu = Counter(a.gorev_id for a in kilitli)

    gorevler = list(NobetGorevi.objects.filter(aktif=True).prefetch_related("izinli_rutbeler", "sabit_uyeler"))
    izinli = {g.pk: {r.pk for r in g.izinli_rutbeler.all()} for g in gorevler}
    aylik = {(k.gorev_id, k.ay): k.kontenjan for k in NobetKontenjani.objects.filter(ay=donem.ay)}
    kontenjan = {g.pk: g.ay_kontenjani(donem.ay, aylik) for g in gorevler}
    adaylar = [p for p in uygun_personel(donem) if p.pk not in dolu_kisi]
    aday_ids = {p.pk for p in adaylar}
    gec = gecmis(donem)
    onceki = onceki_ay_gorevleri(donem)
    yeni = []
    rapor = DagitimRaporu(rutbesiz=Personel.objects.filter(aktif=True, rutbe=None, nobet_durumu=Personel.NOBET_TUTAR).count())

    def yaz(p, g):
        dolu_kisi.add(p.pk)
        gorev_dolu[g.pk] += 1
        yeni.append(NobetAtamasi(donem=donem, gorev=g, personel=p))

    def tekrar(p, g):
        return 1 if (not ayar.ardisik_ayni_gorev and onceki.get(p.pk) == g.pk) else 0

    def sirala(gorev, havuz):
        def anahtar(p):
            g = gec.get(p.pk, Gecmis())
            return (g.yatili if gorev.yatili else 0, tekrar(p, gorev), g.puan, g.gorevler[gorev.pk], _kura(p.pk, donem, gorev.pk))
        return sorted(havuz, key=anahtar)

    def uygunlar(gorev):
        return [p for p in adaylar if p.pk not in dolu_kisi and p.rutbe_id in izinli[gorev.pk]]

    # 1. sabit görevliler (kısıtlaması olmayanlar; rütbe kuralı aranmaz)
    for g in gorevler:
        for p in g.sabit_uyeler.all():
            if p.pk in aday_ids and p.pk not in dolu_kisi:
                yaz(p, g)

    otomatik = [g for g in gorevler if not g.sadece_sabit]
    sinirli = [g for g in otomatik if kontenjan[g.pk] is not None]
    kalan_gorevler = [g for g in otomatik if kontenjan[g.pk] is None]
    yatililar = [g for g in sinirli if g.yatili]
    digerleri = [g for g in sinirli if not g.yatili]

    # 2. yatılı görevler birlikte
    if yatililar:
        ihtiyac = {g.pk: max(kontenjan[g.pk] - gorev_dolu[g.pk], 0) for g in yatililar}
        havuz = [p for p in adaylar if p.pk not in dolu_kisi and any(p.rutbe_id in izinli[g.pk] for g in yatililar)]
        havuz.sort(key=lambda p: (gec.get(p.pk, Gecmis()).yatili, gec.get(p.pk, Gecmis()).puan, _kura(p.pk, donem, 0)))
        for p in havuz:
            acik = [g for g in yatililar if ihtiyac[g.pk] > 0 and p.rutbe_id in izinli[g.pk]]
            if not acik:
                continue
            g_p = gec.get(p.pk, Gecmis())
            if ayar.yatili_tur_dengesi:
                secim = min(acik, key=lambda g: (g_p.gorevler[g.pk], tekrar(p, g), -ihtiyac[g.pk], g.sira))
            else:
                secim = min(acik, key=lambda g: (tekrar(p, g), -ihtiyac[g.pk], g.sira))
            yaz(p, secim)
            ihtiyac[secim.pk] -= 1
        for g in yatililar:
            if ihtiyac[g.pk] > 0:
                rapor.eksik.append((g, ihtiyac[g.pk]))

    # 3. diğer sınırlı görevler: en az adayı olandan
    digerleri.sort(key=lambda g: (len(uygunlar(g)), g.sira))
    for g in digerleri:
        ihtiyac = kontenjan[g.pk] - gorev_dolu[g.pk]
        if ihtiyac <= 0:
            continue
        secilen = sirala(g, uygunlar(g))[:ihtiyac]
        for p in secilen:
            yaz(p, g)
        if len(secilen) < ihtiyac:
            rapor.eksik.append((g, ihtiyac - len(secilen)))

    # 4. "kalan herkes" görevleri: sırayla, her seferinde en az kişisi olan göreve
    if kalan_gorevler:
        sayac = Counter({g.pk: gorev_dolu[g.pk] for g in kalan_gorevler})
        while True:
            ilerledi = False
            for g in sorted(kalan_gorevler, key=lambda g: (sayac[g.pk], g.sira)):
                havuz = uygunlar(g)
                if not havuz:
                    continue
                p = sirala(g, havuz)[0]
                dolu_kisi.add(p.pk)
                sayac[g.pk] += 1
                yeni.append(NobetAtamasi(donem=donem, gorev=g, personel=p))
                ilerledi = True
                break
            if not ilerledi:
                break

    NobetAtamasi.objects.bulk_create(yeni)
    rapor.atanan = len(yeni) + len(kilitli)
    rapor.bosta = [p for p in adaylar if p.pk not in dolu_kisi]
    donem.son_dagitim = timezone.now()
    donem.save(update_fields=["son_dagitim"])
    return rapor


# ---------------------------------------------------------------- elle düzenleme

def _taslak_mi(donem):
    if donem.durum != NobetDonemi.TASLAK:
        raise NobetHatasi("Kesinleşmiş ayda değişiklik yapılamaz. Önce taslağa alın.")


@transaction.atomic
def tasi(atama, gorev):
    _taslak_mi(atama.donem)
    atama.gorev, atama.kilitli = gorev, True
    atama.save(update_fields=["gorev", "kilitli"])


@transaction.atomic
def yer_degistir(a1, a2):
    _taslak_mi(a1.donem)
    if a1.donem_id != a2.donem_id:
        raise NobetHatasi("Farklı aylardaki atamalar değiştirilemez.")
    a1.gorev, a2.gorev = a2.gorev, a1.gorev
    a1.kilitli = a2.kilitli = True
    a1.save(update_fields=["gorev", "kilitli"])
    a2.save(update_fields=["gorev", "kilitli"])


@transaction.atomic
def ekle(donem, personel, gorev):
    _taslak_mi(donem)
    if NobetAtamasi.objects.filter(donem=donem, personel=personel).exists():
        raise NobetHatasi(f"{personel.ad_soyad} bu ay zaten bir gruba yazılı.")
    return NobetAtamasi.objects.create(donem=donem, personel=personel, gorev=gorev, kilitli=True)


@transaction.atomic
def cikar(atama):
    _taslak_mi(atama.donem)
    atama.delete()


# ---------------------------------------------------------------- adalet kontrolü

def adalet_uyarilari(donem):
    """Bu ay dahil, aynı rütbedeki personelin yatılı sayıları arasındaki fark sınırı aşıyor mu?"""
    ayar = NobetAyari.al()
    gec = gecmis(donem, dahil=True)
    havuz = list(uygun_personel(donem))
    rutbeler = defaultdict(list)
    for p in havuz:
        rutbeler[p.rutbe].append((p, gec.get(p.pk, Gecmis()).yatili))
    uyarilar = []
    for rutbe, liste in rutbeler.items():
        if len(liste) < 2:
            continue
        en_az, en_cok = min(s for _, s in liste), max(s for _, s in liste)
        if en_cok - en_az > ayar.yatili_fark_siniri:
            uyarilar.append({
                "rutbe": rutbe, "en_az": en_az, "en_cok": en_cok, "fark": en_cok - en_az, "sinir": ayar.yatili_fark_siniri,
                "az_olanlar": [p for p, s in liste if s == en_az][:5],
                "cok_olanlar": [p for p, s in liste if s == en_cok][:5],
            })
    return uyarilar


def kural_disi_atamalar(donem):
    """Elle yapılmış ama görevin rütbe kuralına uymayan atamalar (bilgi amaçlı)."""
    sonuc = []
    for a in donem.atamalar.select_related("gorev", "personel__rutbe").prefetch_related("gorev__izinli_rutbeler"):
        izinli = {r.pk for r in a.gorev.izinli_rutbeler.all()}
        if a.personel.rutbe_id not in izinli:
            sonuc.append(a)
    return sonuc


# ---------------------------------------------------------------- puantaj

def puantaj(yil_basi):
    """Nöbet yılının 12 ayı için kişi × ay tablosu (kesin + taslak aylar, taslaklar ayrıca işaretli)."""
    ayar = NobetAyari.al()
    aylar = nobet_yili_donemleri(yil_basi, ayar.yil_baslangic_ayi)
    donemler = {(d.yil, d.ay): d for d in NobetDonemi.objects.filter(yil__in={y for y, _ in aylar})}
    donemler = {k: v for k, v in donemler.items() if k in aylar}
    satirlar = defaultdict(lambda: {"aylar": {}, "puan": Decimal(0), "yatili": 0, "kesin_puan": Decimal(0)})
    for a in NobetAtamasi.objects.filter(donem__in=donemler.values()).select_related("gorev", "donem", "personel__rutbe", "personel__sinif", "personel__unvan"):
        s = satirlar[a.personel]
        s["aylar"][(a.donem.yil, a.donem.ay)] = a
        s["puan"] += a.gorev.puan
        s["yatili"] += 1 if a.gorev.yatili else 0
    return aylar, donemler, satirlar


def ay_adi(yil, ay):
    return f"{AYLAR[ay - 1]} {yil}"


# ---------------------------------------------------------------- yıllık plan

def yil_aylari(yil_basi):
    return nobet_yili_donemleri(yil_basi, NobetAyari.al().yil_baslangic_ayi)


def yil_olustur(yil_basi, kullanici=None, baslangic=None):
    """Nöbet yılının aylarını sırayla oluşturur/yeniden dağıtır. Kesinleşmiş aylar atlanır, kilitli atamalar korunur.

    baslangic=(yıl, ay) verilirse o aydan önceki aylara dokunulmaz.
    """
    sonuc = []
    for y, a in yil_aylari(yil_basi):
        if baslangic and (y, a) < baslangic:
            continue
        d, _ = NobetDonemi.objects.get_or_create(yil=y, ay=a, defaults={"olusturan": kullanici})
        if d.durum == NobetDonemi.KESIN:
            continue
        sonuc.append((d, dagit(d)))
    return sonuc


@transaction.atomic
def hucre_ata(personel, yil, ay, gorev, kullanici=None):
    """Yıllık plandan bir kişinin bir aydaki görevini değiştirir (gorev=None → gruptan çıkar)."""
    if gorev is None and not NobetDonemi.objects.filter(yil=yil, ay=ay).exists():
        raise NobetHatasi("Bu ay henüz oluşturulmadı.")
    d, _ = NobetDonemi.objects.get_or_create(yil=yil, ay=ay, defaults={"olusturan": kullanici})
    _taslak_mi(d)
    mevcut = NobetAtamasi.objects.filter(donem=d, personel=personel).first()
    if gorev is None:
        if mevcut:
            mevcut.delete()
        return d, None
    if mevcut:
        tasi(mevcut, gorev)
        return d, mevcut
    return d, ekle(d, personel, gorev)


@transaction.atomic
def ay_engelle(personel, yil, ay, kullanici=None, aciklama=""):
    """Kişiyi sadece bu ay için "yazılamaz" yapar; varsa o ayki ataması silinir."""
    d = NobetDonemi.objects.filter(yil=yil, ay=ay).first()
    if d:
        _taslak_mi(d)
        NobetAtamasi.objects.filter(donem=d, personel=personel).delete()
    ilk, son = ay_araligi(yil, ay)
    return NobetKisitlamasi.objects.create(personel=personel, tur="yazilamaz", baslangic=ilk, bitis=son,
                                           aciklama=aciklama, olusturan=kullanici)


@transaction.atomic
def ay_engel_kaldir(personel, yil, ay):
    """Sadece bu ayı kapsayan "yazılamaz" işaretlerini kaldırır. Daha uzun kısıtlamalar Kısıtlamalar ekranından düzenlenir."""
    ilk, son = ay_araligi(yil, ay)
    tek_ay = NobetKisitlamasi.objects.filter(personel=personel, tur="yazilamaz", baslangic__gte=ilk, bitis__lte=son)
    tek_ay.delete()
    kalan = ay_kisitlamalari(yil, ay).get(personel.pk)
    if kalan:
        raise NobetHatasi(f"Bu ay {kalan.get_tur_display()} kısıtlaması var ({kalan}); Kısıtlamalar ekranından düzenleyin.")


def yil_kisitlamalari(yil_basi):
    """Nöbet yılı boyunca {(personel_id, yıl, ay): kısıtlama}."""
    aylar = yil_aylari(yil_basi)
    bas, _ = ay_araligi(*aylar[0])
    _, bit = ay_araligi(*aylar[-1])
    sonuc = {}
    for k in NobetKisitlamasi.objects.filter(baslangic__lte=bit).filter(Q(bitis=None) | Q(bitis__gte=bas)).order_by("baslangic"):
        for y, a in aylar:
            ilk, son = ay_araligi(y, a)
            if k.baslangic <= son and (k.bitis is None or k.bitis >= ilk):
                sonuc.setdefault((k.personel_id, y, a), k)
    return sonuc


def muaf_etiketi(personel, yil, ay, kisitlamalar=None):
    """Bu ay nöbete giremiyorsa kısa nedeni (TAYİN, YDGG, ✕, MUAF ...), girebiliyorsa None."""
    if kisitlamalar is not None:
        k = kisitlamalar.get((personel.pk, yil, ay))
    else:
        k = ay_kisitlamalari(yil, ay).get(personel.pk)
    if k:
        return k.etiket
    if personel.nobet_durumu == Personel.NOBET_TUTAMAZ:
        return "TUTAMAZ"
    if personel.nobet_durumu == Personel.NOBET_MUAF and (
            personel.nobet_muafiyet_bitis is None or personel.nobet_muafiyet_bitis >= date(yil, ay, 1)):
        return (personel.nobet_muafiyet_nedeni or "MUAF").upper()[:10]
    return None


def muaf_mi(personel, yil, ay):
    return muaf_etiketi(personel, yil, ay) is not None


def rutbe_ozeti(satirlar, sinir):
    """satirlar: [(personel, {"puan", "yatili"})] → rütbe bazında en az/en çok yatılı ve puan."""
    gruplar = defaultdict(list)
    for p, s in satirlar:
        gruplar[p.rutbe].append(s)
    ozet = []
    for rutbe, liste in gruplar.items():
        yat = [s["yatili"] for s in liste]
        pu = [s["puan"] for s in liste]
        ozet.append({"rutbe": rutbe, "kisi": len(liste), "yat_min": min(yat), "yat_max": max(yat),
                     "fark": max(yat) - min(yat), "asim": max(yat) - min(yat) > sinir,
                     "puan_min": min(pu), "puan_max": max(pu)})
    return sorted(ozet, key=lambda o: -(o["rutbe"].pk if o["rutbe"] else 0))