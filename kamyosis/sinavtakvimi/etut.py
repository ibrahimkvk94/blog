"""Etüt görevlendirmeleri (Sınav İcrası 3. sekme): sınav gününden bir önceki gün (hafta içi / sonu fark etmez) etüde
gelecek öğretim elemanları. Planın her ders × program satırına bir kişi yazılır, isteğe bağlı ikincisi eklenir. Herkes
görür; bölüm hesabı kendi programının ya da verdiği dersin satırını, Sınav İcrası yetkilisi hepsini girer. Öneri,
kesinleştirme ve puantaj yoktur."""

import datetime

from django.db import transaction

from personel.models import Personel

from . import servis
from .models import Etut


def adaylar():
    """Seçilebilecek öğretim elemanları: okulun derse giren tüm aktif personeli."""
    return list(Personel.objects.filter(aktif=True, derse_girebilir=True)
                .select_related("bolum", "unvan", "rutbe", "sinif").order_by("ad_soyad"))


def kisi_sozlugu(p):
    return {"id": p.pk, "ad": str(p), "bolum": (p.bolum.kod or p.bolum.ad) if p.bolum_id else ""} if p else None


def satirlar(takvim, yetki=None):
    """Planın her ders × program satırı (bir kez) ve yazılan öğretim elemanları; etüt günü = sınavdan önceki gün."""
    from personel.models import Bolum

    kayitlar = {(e.kod, e.bolum): e for e in takvim.etutler.select_related(
        "ogretmen1__unvan", "ogretmen1__rutbe", "ogretmen1__sinif", "ogretmen1__bolum",
        "ogretmen2__unvan", "ogretmen2__rutbe", "ogretmen2__sinif", "ogretmen2__bolum")}
    bolumler = servis.ders_bolumleri()
    adlar = dict(Bolum.objects.exclude(kod=None).values_list("kod", "ad"))
    out, gorulen = [], set()
    for s in takvim.satirlar.all():
        anahtar = (s.kod, s.bolum)
        if anahtar in gorulen or not s.kod:
            continue
        gorulen.add(anahtar)
        e = kayitlar.get(anahtar)
        o = servis.onek(s.kod)
        db = bolumler.get(o)
        o1 = e.ogretmen1 if e else None
        o2 = e.ogretmen2 if e else None
        etut_gunu = s.tarih - datetime.timedelta(days=1)
        out.append({"no": len(out) + 1, "satir": s, "kod": s.kod, "ders": s.ders, "ad": servis.tr_baslik(s.ders),
                    "bolum": s.bolum, "bolum_adi": adlar.get(s.bolum, s.bolum), "sinif": s.sinif,
                    "ders_bolumu": db.kod if db and db.kod else o, "ders_bolumu_adi": db.ad if db else o,
                    "etut_gunu": etut_gunu, "o1": o1, "o2": o2, "girildi": o1 is not None,
                    "girebilir": yetki.girebilir(s.bolum, o) if yetki else False})
    return out


def gunler(satir_listesi):
    """Etüt günleri (sırayla) ve her günün dolu / toplam sayısı."""
    out = {}
    for r in satir_listesi:
        g = out.setdefault(r["etut_gunu"], {"tarih": r["etut_gunu"], "toplam": 0, "girilen": 0,
                                              "ad": servis.GUNLER[r["etut_gunu"].weekday()],
                                              "sinav_gunu": r["satir"].tarih})
        g["toplam"] += 1
        g["girilen"] += r["girildi"]
    return [out[k] for k in sorted(out)]


@transaction.atomic
def kaydet(takvim, kod, bolum, ogretmen1, ogretmen2, user):
    """ogretmen1/2: Personel kimliği ya da None. İkinci tek başına kalırsa birinci olur; aynı kişi iki kez yazılmaz."""
    gecerli = set(Personel.objects.filter(aktif=True, derse_girebilir=True).values_list("pk", flat=True))
    idler = []
    for x in (ogretmen1, ogretmen2):
        try:
            x = int(x) if x not in (None, "") else None
        except (TypeError, ValueError):
            raise servis.TakvimHatasi("Öğretim elemanı geçersiz.") from None
        if x is not None:
            if x not in gecerli:
                raise servis.TakvimHatasi("Bu kişi seçilebilecek öğretim elemanları arasında değil.")
            if x not in idler:
                idler.append(x)
    if not idler:
        Etut.objects.filter(takvim=takvim, kod=kod, bolum=bolum).delete()
        return None
    e, _ = Etut.objects.update_or_create(takvim=takvim, kod=kod, bolum=bolum, defaults={
        "ogretmen1_id": idler[0], "ogretmen2_id": idler[1] if len(idler) > 1 else None, "guncelleyen": user})
    return Etut.objects.select_related("ogretmen1__unvan", "ogretmen1__rutbe", "ogretmen1__sinif", "ogretmen1__bolum",
                                       "ogretmen2__unvan", "ogretmen2__rutbe", "ogretmen2__sinif",
                                       "ogretmen2__bolum").get(pk=e.pk)


def excel(takvim, satir_listesi):
    """Okulun “Akşam etütlerinde görevli personel listesi” biçimi; sınav ve etüt tarihleri gün gün birleşik."""
    yil, metin = servis.plan_basligi(takvim)
    satirlar = []
    for i, r in enumerate(satir_listesi, start=1):
        kisiler = "\n".join(str(o) for o in (r["o1"], r["o2"]) if o)
        satirlar.append([i, r["sinif"], r["kod"], servis.buyuk_tr(r["ders"]), servis.buyuk_tr(r["bolum_adi"]), kisiler,
                         servis.tarih_resmi(r["satir"].tarih), servis.tarih_resmi(r["etut_gunu"])])
    return servis.resmi_liste_excel(
        f"{yil} EĞİTİM VE ÖĞRETİM YILI\n{metin} AKŞAM ETÜTLERİNDE GÖREVLİ PERSONEL LİSTESİ",
        ["S.NO", "SINIF", "DERS KODU", "DERS ADI", "SINAVIN YAPILACAĞI PROGRAM",
         "GÖREVLENDİRİLEN PERSONEL\n(RÜTBE/ÜNVAN-ADI-SOYADI)", "SINAV TARİHİ", "ETÜT TARİHİ"],
        satirlar, [9, 10, 14, 44, 40, 42, 20, 20], ortalar=(1, 2, 3, 7, 8), birlesik=(7, 8))
