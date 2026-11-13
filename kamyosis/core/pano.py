"""Ana sayfadaki yönetici gösterge paneli ("Bugün okulda"): personel durumu, yoklama, dersler, sınavlar, salonlar.

Yalnız sistem yöneticileri görür. Her bölüm ayrı hesaplanır; biri hata verirse (ör. modül verisi yok) o kart
görünmez, ana sayfa yine açılır.
"""

import datetime
import logging
from collections import Counter, defaultdict

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

log = logging.getLogger(__name__)

GUN_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
AY_KISA = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
EGILIM_GUN = 15  # iş günü


def _url(ad, *args):
    try:
        return reverse(ad, args=args)
    except NoReverseMatch:
        return ""


def _kisa_ad(ad):
    for ek in (" Şube Müdürlüğü", " Müdürlüğü", " Koordinatörlüğü", " Kısmı"):
        if ad.endswith(ek):
            return ad[: -len(ek)]
    return ad


def _guvenli(f, *args):
    try:
        return f(*args)
    except Exception:  # bir kartın verisi bozuksa panel yine açılır
        log.exception("Gösterge paneli: %s hesaplanamadı", getattr(f, "__name__", f))
        return None


def _hafta(bugun):
    """Hafta içiyse bu hafta, hafta sonuysa gelecek hafta (Pzt–Paz)."""
    pzt = bugun - datetime.timedelta(days=bugun.weekday())
    if bugun.weekday() >= 5:
        return pzt + datetime.timedelta(days=7), "Gelecek hafta"
    return pzt, "Bu hafta"


# ---------------------------------------------------------------- personel

def _grup(agac, bid):
    """Kişinin panelde gösterildiği küme: bölüm, şube müdürlüğü ya da yönetim."""
    if not bid:
        return ("yersiz", "Teşkilatta yeri yok", "idari", 9999)
    zincir = agac.zincir(bid)
    for i, b in enumerate(zincir):
        if b.bolum_id:
            return (f"b{b.pk}", _kisa_ad(b.ad), "akademik", i * 1000 + b.sira)
    if len(zincir) >= 3:
        b = zincir[2]
        return (f"b{b.pk}", _kisa_ad(b.ad), "idari", b.sira)
    return ("yonetim", "Yönetim ve koordinatörlük", "idari", -1)


def personel(request, bugun):
    from yoklama import servis as ys

    y = ys.yetki(request)
    agac = y.agac
    kisiler = list(ys.personeller(y))
    durumlar = ys.gun_durumu(bugun, kisiler)
    gruplar, turler = {}, {}
    for d in durumlar:
        anahtar, ad, tur, sira = _grup(agac, agac.kisi_birimi(d.personel))
        g = gruplar.setdefault(anahtar, {"ad": ad, "tur": tur, "sira": sira, "kisiler": [], "yok": 0})
        kayit = d.kayitlar[0] if d.kayitlar else None
        if kayit:
            turler.setdefault(kayit.tur_id, {"tur": kayit.tur, "sayi": 0})["sayi"] += 1
            g["yok"] += 1
        p = d.personel
        g["kisiler"].append({
            "ad": p.ad_soyad, "mevcut": d.mevcut, "kismi": d.kismi,
            "renk": kayit.tur.renk if kayit else "", "tur": kayit.tur.ad if kayit else "",
            "saat": "" if (not kayit or d.gun_boyu) else
            f"{timezone.localtime(kayit.baslangic):%H:%M}–{timezone.localtime(kayit.bitis):%H:%M}",
            "url": _url("yoklama:kart", p.pk),
        })
    for g in gruplar.values():  # yokları başa al: göz önce onları görsün
        g["kisiler"].sort(key=lambda k: (k["mevcut"], k["tur"], k["ad"]))
    sirali = sorted(gruplar.values(), key=lambda g: g["sira"])
    toplam, mevcut = len(durumlar), sum(d.mevcut for d in durumlar)
    gun_boyu, kismi = sum(d.gun_boyu for d in durumlar), sum(d.kismi for d in durumlar)

    ozetler = [o for o in ys.birim_ozetleri(y, bugun) if o["toplam"] and o["birim"].pk]
    kesin = sum(1 for o in ozetler if o["onay"])
    return {
        "toplam": toplam, "mevcut": mevcut, "gun_boyu": gun_boyu, "kismi": kismi,
        "oran": round(mevcut * 100 / toplam) if toplam else 0,
        "idari": [g for g in sirali if g["tur"] == "idari"],
        "akademik": [g for g in sirali if g["tur"] == "akademik"],
        "turler": sorted(turler.values(), key=lambda t: (t["tur"].sira, t["tur"].ad)),
        "yoklama": {"kesin": kesin, "birim": len(ozetler), "oran": round(kesin * 100 / len(ozetler)) if ozetler else 0,
                    "eksik": [o["birim"].ad for o in ozetler if not o["onay"]]},
        "url": _url("yoklama:ana"),
    }


def egilim(request, bugun):
    """Son iş günlerinde gün boyu yok ve kısmi yok sayısı (sütun grafiği)."""
    from yoklama import servis as ys

    y = ys.yetki(request)
    gunler, d = [], bugun
    while len(gunler) < EGILIM_GUN:
        if d.weekday() < 5:
            gunler.append(d)
        d -= datetime.timedelta(days=1)
    gunler.reverse()
    _, _, gun_ozet = ys.takvim(gunler[0], gunler[-1], list(ys.personeller(y)))
    by = {g["tarih"]: g for g in gun_ozet}
    sutunlar = [{"tarih": g, "gun": GUN_KISA[g.weekday()], "etiket": f"{g.day} {AY_KISA[g.month - 1]}",
                 "yok": by[g]["yok"], "kismi": by[g]["kismi"], "bugun": g == bugun} for g in gunler]
    tepe = max([s["yok"] + s["kismi"] for s in sutunlar] + [1])
    olcek = _olcek(tepe)
    for s in sutunlar:
        s["yok_boy"] = _yuzde(s["yok"], olcek)
        s["kismi_boy"] = _yuzde(s["kismi"], olcek)
    return {"sutunlar": sutunlar, "olcek": olcek, "cizgiler": [olcek, olcek // 2] if olcek > 1 else [olcek],
            "ortalama": round(sum(s["yok"] for s in sutunlar) / len(sutunlar), 1)}


def _yuzde(pay, payda):
    """CSS için yüzde metni (yerel ayarın ondalık virgülünden bağımsız, ör. "48.84")."""
    return f"{pay * 100 / payda:.2f}" if payda else "0"


def _olcek(tepe):
    """Eksen tepesi: tepeyi aşan en küçük 'yuvarlak' sayı (2, 4, 6, 10, 20 …)."""
    for adim in (2, 4, 6, 8, 10, 12, 16, 20, 30, 40, 50, 60, 80, 100, 150, 200, 300):
        if tepe <= adim:
            return adim
    return tepe


# ---------------------------------------------------------------- dersler

def dersler(bugun):
    from takip.servis import beklenen_dersler

    pzt, baslik = _hafta(bugun)
    satirlar = beklenen_dersler(pzt, pzt + datetime.timedelta(days=6))
    bolumler, gunler = Counter(), Counter()
    saatler, kisiler = set(), set()
    for s in satirlar:
        bolumler[s.bolum.ad if s.bolum else "Bölümü belirsiz"] += 1
        gunler[s.tarih] += 1
        saatler.add((s.tarih, s.hucre.pk))
        kisiler.add(s.etkin_personel.pk if s.etkin_personel else f"o{s.ogretmen.pk}")
    tepe = max(bolumler.values(), default=1)
    gun_tepe = max(gunler.values(), default=1)
    bugun_n = sum(1 for s in satirlar if s.tarih == bugun)
    return {
        "baslik": baslik, "bas": pzt, "bit": pzt + datetime.timedelta(days=4),
        "toplam": len(satirlar), "saat": len(saatler), "kisi": len(kisiler), "bugun": bugun_n,
        "bolumler": [{"ad": ad, "sayi": n, "boy": _yuzde(n, tepe)} for ad, n in bolumler.most_common()],
        "gunler": [{"gun": GUN_KISA[i], "tarih": pzt + datetime.timedelta(days=i),
                    "sayi": gunler.get(pzt + datetime.timedelta(days=i), 0),
                    "boy": _yuzde(gunler.get(pzt + datetime.timedelta(days=i), 0), gun_tepe),
                    "bugun": pzt + datetime.timedelta(days=i) == bugun} for i in range(5)],
        "url": _url("takip:gunluk"),
    }


# ---------------------------------------------------------------- sınavlar

def sinavlar(bugun):
    from sinav.models import ExamPeriod, ExamPlacement

    donem = (ExamPeriod.objects.filter(end_date__gte=bugun).order_by("start_date", "id").first())
    if donem is None:
        return None
    yerlesimler = list(ExamPlacement.objects.filter(exam__period=donem)
                       .select_related("exam__subject").prefetch_related("rooms__proctors", "exam__classes"))
    oturumlar = donem.session_times
    gunler = donem.dates()
    hucre = defaultdict(list)
    eksik_salon, salon_sayisi, ogrenci = 0, 0, 0
    for p in yerlesimler:
        hucre[(p.date, p.session)].append(p)
        for r in p.rooms.all():
            salon_sayisi += 1
            ogrenci += r.seats
            if len(r.proctors.all()) < donem.proctors_per_room:
                eksik_salon += 1
    tepe = max((len(v) for v in hucre.values()), default=1)
    satirlar = []
    for i, saat in enumerate(oturumlar):
        satir = {"saat": saat, "hucreler": []}
        for g in gunler:
            ps = hucre.get((g, i), [])
            ad = [p.exam.name or p.exam.subject.name for p in ps]
            satir["hucreler"].append({
                "sayi": len(ps), "kademe": 0 if not ps else min(5, 1 + (len(ps) - 1) * 5 // max(tepe, 1)),
                "ipucu": f"{g:%d.%m} {saat} · {len(ps)} sınav" + (": " + ", ".join(sorted(ad)[:8]) + (" …" if len(ad) > 8 else "") if ad else ""),
            })
        satirlar.append(satir)
    gun_sayilari = [sum(1 for p in yerlesimler if p.date == g) for g in gunler]
    kalan = (donem.start_date - bugun).days
    try:
        url = reverse("sinav:results", args=[donem.school_id, donem.pk])
    except NoReverseMatch:
        url = ""
    return {
        "donem": donem, "kalan": kalan, "suruyor": donem.start_date <= bugun <= donem.end_date,
        "sinav": donem.exams.count(), "yerlesen": len(yerlesimler), "salon": salon_sayisi, "ogrenci": ogrenci,
        "eksik_salon": eksik_salon,
        "gunler": [{"gun": GUN_KISA[g.weekday()], "etiket": f"{g:%d.%m}", "sayi": n, "bugun": g == bugun}
                   for g, n in zip(gunler, gun_sayilari)],
        "satirlar": satirlar, "url": url,
    }


# ---------------------------------------------------------------- salonlar

def salonlar():
    from salon import servis as ss

    simdi = timezone.localtime()
    out = []
    for d in ss.simdiki_durum(ss.salonlar(), simdi):
        k, s = d["su_an"], d["siradaki"]
        out.append({"salon": d["salon"], "dolu": k is not None,
                    "metin": (f"{k.baslik} · {k.saat_metni}" if k else
                              (f"Sıradaki: {s.baslik} · {s.saat_metni}" if s else "Bugün boş"))})
    if not out:
        return None
    return {"liste": out, "dolu": sum(x["dolu"] for x in out), "url": _url("salon:yil")}


# ---------------------------------------------------------------- hepsi

def hazirla(request):
    bugun = timezone.localdate()
    return {
        "bugun": bugun, "hafta_sonu": bugun.weekday() >= 5,
        "personel": _guvenli(personel, request, bugun),
        "egilim": _guvenli(egilim, request, bugun),
        "dersler": _guvenli(dersler, bugun),
        "sinavlar": _guvenli(sinavlar, bugun),
        "salonlar": _guvenli(salonlar),
    }
