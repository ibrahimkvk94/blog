"""İstatistikler sayfası, Personel sekmesi: kadro yapısı (subay / astsubay / sivil), rütbe, akademik unvan, sınıf ve
birimlere göre dağılım; kart alanlarından öğrenim ve kadro durumu; kapasiteye göre kadro doluluğu.
Veri: personel kartlarındaki rütbe, sınıf, unvan ve ek alanlar (aktif personel)."""

from collections import Counter, defaultdict

from personel.models import AKADEMIK_UNVANLAR, MEMUR_UNVANLARI, KartAlani, KartDegeri, Personel, Secenek

from .models import KadroKapasitesi

from .pano import _grup, _yuzde

# Kadro türleri: renkler açıklıkça ayrışır (koyu lacivert, orta camgöbeği, açık altın) — renk körlüğünde de seçilir.
# Değerler CSS'te (.pn --pn-subay …), koyu temada ayrı tonlarla.
TURLER = [
    {"kod": "subay", "ad": "Subay", "renk": "var(--pn-subay)"},
    {"kod": "astsubay", "ad": "Astsubay", "renk": "var(--pn-astsubay)"},
    {"kod": "sivil", "ad": "Sivil", "renk": "var(--pn-sivil)"},
]
# Kart alanları (personel/migrations/0017): adları değişirse istatistik "alan bulunamadı" der.
OGRENIM_ALANI, KADRO_ALANI = "Öğrenim durumu", "Kadro durumu"
SIVIL_ALT = [("memur", "Devlet memuru"), ("akademik", "Sivil öğretim elemanı"), ("diger", "Diğer")]


def kadro_turu(p):
    rutbe = str(p.rutbe or "").strip()
    if rutbe:
        return "astsubay" if rutbe.startswith("Asb") else "subay"
    return "sivil"


def sivil_alt(p):
    unvan = str(p.unvan or "").strip()
    if unvan in MEMUR_UNVANLARI:
        return "memur"
    if unvan in AKADEMIK_UNVANLAR:
        return "akademik"
    return "diger"


def _cubuklar(sayac, sira=None, renk="var(--pn-lacivert)"):
    """Yatay çubuk listesi: [{ad, sayi, boy, renk}] — sira verilirse o sırayla, yoksa çoktan aza."""
    if sira is None:
        anahtarlar = [a for a, _ in sayac.most_common()]
    else:
        anahtarlar = [a for a in sira if sayac.get(a)] + [a for a in sayac if a not in sira]
    tepe = max(sayac.values(), default=1)
    return [{"ad": a, "sayi": sayac[a], "boy": _yuzde(sayac[a], tepe), "renk": renk} for a in anahtarlar]


def _parcali(sayac_turler, sira):
    """Kadro türlerine bölünmüş yatay çubuklar (birim çubuğuyla aynı yapı): [{ad, toplam, boy, parcalar}]."""
    tepe = max((sum(c.values()) for c in sayac_turler.values()), default=1) or 1
    out = []
    for ad in [a for a in sira if sayac_turler.get(a)] + [a for a in sayac_turler if a not in sira]:
        c = sayac_turler[ad]
        n = sum(c.values())
        out.append({"ad": ad, "toplam": n, "boy": _yuzde(n, tepe),
                    "parcalar": [{"ad": t["ad"], "sayi": c[t["kod"]], "boy": _yuzde(c[t["kod"]], n), "renk": t["renk"]}
                                 for t in TURLER if c[t["kod"]]]})
    return out


def kart_dagilimi(ad, kisiler):
    """Bir seçim alanının (ör. Öğrenim durumu) dağılımı, kadro türüne bölünmüş. Alan yoksa None."""
    alan = KartAlani.objects.filter(ad=ad, aktif=True).first()
    if alan is None:
        return None
    tur = {p.pk: kadro_turu(p) for p in kisiler}
    degerler = dict(KartDegeri.objects.filter(alan=alan, personel_id__in=tur).exclude(deger="")
                    .values_list("personel_id", "deger"))
    sayac = defaultdict(Counter)
    for pid, d in degerler.items():
        sayac[d][tur[pid]] += 1
    return {"ad": alan.ad, "girilen": len(degerler), "girilmemis": len(kisiler) - len(degerler),
            "oran": round(len(degerler) * 100 / len(kisiler)) if kisiler else 0,
            "satirlar": _parcali(sayac, alan.secenek_listesi)}


def doluluk(turler, toplam):
    """Kadro doluluğu: aktif personel / kapasite — toplam ve (girildiyse) türlere göre."""
    k = KadroKapasitesi.al()

    def satir(ad, mevcut, kapasite, renk):
        if not kapasite:
            return {"ad": ad, "mevcut": mevcut, "kapasite": None, "renk": renk}
        return {"ad": ad, "mevcut": mevcut, "kapasite": kapasite, "renk": renk,
                "oran": round(mevcut * 100 / kapasite), "boy": _yuzde(min(mevcut, kapasite), kapasite),
                "bos": max(kapasite - mevcut, 0), "fazla": max(mevcut - kapasite, 0)}

    genel = satir("Toplam", toplam, k.genel_toplam, "var(--pn-lacivert)")
    return {"kayit": k, "genel": genel,
            "turler": [satir(t["ad"], turler[t["kod"]], getattr(k, t["kod"]), t["renk"]) for t in TURLER
                       if getattr(k, t["kod"])]}


def kadro():
    from yoklama.birim import Agac

    kisiler = list(Personel.objects.filter(aktif=True).select_related("rutbe", "sinif", "unvan", "bolum"))
    toplam = len(kisiler)
    turler = Counter(kadro_turu(p) for p in kisiler)
    siviller = Counter(sivil_alt(p) for p in kisiler if kadro_turu(p) == "sivil")

    sira = {t: list(Secenek.objects.filter(tur=t).order_by("sira", "metin").values_list("metin", flat=True))
            for t in (Secenek.RUTBE, Secenek.UNVAN, Secenek.SINIF)}
    rutbeler = Counter(str(p.rutbe) for p in kisiler if p.rutbe)
    unvanlar = Counter(str(p.unvan) for p in kisiler if p.unvan and str(p.unvan) in AKADEMIK_UNVANLAR)
    siniflar = Counter(str(p.sinif) for p in kisiler if p.sinif)
    ogretim = sum(1 for p in kisiler if p.derse_girebilir)
    doktora = sum(1 for p in kisiler if "Dr." in str(p.unvan or "") or str(p.unvan or "").startswith("Prof")
                  or str(p.unvan or "").startswith("Doç"))

    renk = {t["kod"]: t["renk"] for t in TURLER}
    rutbe_cubuklari = _cubuklar(rutbeler, sira[Secenek.RUTBE][::-1], renk["subay"])  # kıdemliden başlar
    for c in rutbe_cubuklari:
        if c["ad"].startswith("Asb"):
            c["renk"] = renk["astsubay"]
    agac = Agac()
    gruplar = {}
    for p in kisiler:
        anahtar, ad, tur, gsira = _grup(agac, agac.kisi_birimi(p))
        g = gruplar.setdefault(anahtar, {"ad": ad, "tur": tur, "sira": gsira, "sayac": Counter()})
        g["sayac"][kadro_turu(p)] += 1
    tepe = max((sum(g["sayac"].values()) for g in gruplar.values()), default=1)
    birimler = []
    for g in sorted(gruplar.values(), key=lambda g: g["sira"]):
        n = sum(g["sayac"].values())
        birimler.append({
            "ad": g["ad"], "tur": g["tur"], "toplam": n, "boy": _yuzde(n, tepe),
            "parcalar": [{"ad": t["ad"], "sayi": g["sayac"][t["kod"]], "boy": _yuzde(g["sayac"][t["kod"]], n),
                          "renk": t["renk"]} for t in TURLER if g["sayac"][t["kod"]]],
        })

    return {
        "toplam": toplam, "ogretim": ogretim, "doktora": doktora,
        "doluluk": doluluk(turler, toplam),
        "ogrenim": kart_dagilimi(OGRENIM_ALANI, kisiler),
        "kadro_durumu": kart_dagilimi(KADRO_ALANI, kisiler),
        "turler": [dict(t, sayi=turler[t["kod"]], oran=round(turler[t["kod"]] * 100 / toplam) if toplam else 0,
                        boy=_yuzde(turler[t["kod"]], toplam)) for t in TURLER],
        "siviller": [{"ad": ad, "sayi": siviller[k]} for k, ad in SIVIL_ALT if siviller[k]],
        "rutbeler": rutbe_cubuklari,
        "unvanlar": _cubuklar(unvanlar, sira[Secenek.UNVAN], "var(--pn-camgobegi)"),
        "siniflar": _cubuklar(siniflar, None, "var(--pn-lacivert)"),
        "birimler_idari": [b for b in birimler if b["tur"] == "idari"],
        "birimler_akademik": [b for b in birimler if b["tur"] == "akademik"],
    }
