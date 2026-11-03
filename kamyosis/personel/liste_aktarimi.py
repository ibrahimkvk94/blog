"""Personel listesinden (Excel veya CSV) rütbe, sınıf, unvan, bölüm ve sicil aktarımı.

"Sınıf / rütbe / unvan" sütunu şu biçimlerdedir:
    Öğ.Ütğm.            → sınıf Öğ.,     rütbe Ütğm.
    TopçuAtğm.          → sınıf Topçu,   rütbe Atğm.
    P.Asb.Kd.Bçvş.      → sınıf P.,      rütbe Asb.Kd.Bçvş.
    Doç.Dr. Öğ.Yzb.     → unvan Doç.Dr., sınıf Öğ., rütbe Yzb.
    Öğ.Ütğm. Dr.        → unvan Dr.,     sınıf Öğ., rütbe Ütğm.
    Öğt.Gör.            → unvan Öğt.Gör.
Aynı kişi iki satırda geçiyorsa (ör. Beden Eğitimi ve Spor'da da ders veriyorsa) asıl bölüm
diğer satırdan alınır.
"""

import csv
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from program.asc import ad_anahtari

from .models import Bolum, Personel, Secenek

UNVANLAR = ["Prof.Dr.", "Doç.Dr.", "Dr.Öğt.Üyesi", "Öğt.Gör.Dr.", "Öğt.Gör.", "Doç.", "Dr."]
BES = "Beden Eğitimi ve Spor"
BOS_SICIL = {"", "xxxx", "XXXX", "-", "–"}


@dataclass
class Ayrisim:
    unvan: str = ""
    sinif: str = ""
    rutbe: str = ""
    cozulemeyen: str = ""


def ayristir(metin, rutbeler):
    """Sınıf/rütbe/unvan metnini parçalarına ayırır. rutbeler: bilinen rütbe metinleri."""
    kalan = " ".join((metin or "").split())
    sonuc = Ayrisim()
    for u in UNVANLAR:  # uzundan kısaya: "Öğt.Gör.Dr." "Öğt.Gör."dan önce
        if u == "Dr.":
            parcalar = kalan.split(" ")
            if "Dr." in parcalar:
                sonuc.unvan = sonuc.unvan or "Dr."
                parcalar.remove("Dr.")
                kalan = " ".join(parcalar)
            continue
        if u in kalan:
            sonuc.unvan = sonuc.unvan or u
            kalan = kalan.replace(u, " ", 1)
    kalan = " ".join(kalan.split())
    if not kalan:
        return sonuc
    for r in sorted(rutbeler, key=len, reverse=True):
        if kalan.endswith(r):
            onceki = kalan[: -len(r)]
            # "Ütğm." sonu "Tğm." ile karışmasın: rütbe kelime/nokta sınırında başlamalı
            if onceki and not (onceki.endswith((".", " ")) or onceki[-1].isalpha() and r[0].isupper()):
                continue
            sonuc.rutbe = r
            sonuc.sinif = onceki.strip()
            return sonuc
    sonuc.cozulemeyen = kalan
    return sonuc


@dataclass
class Satir:
    satir: str
    bolum: str
    sru: str
    ad: str
    sicil: str


def oku(yol):
    """CSV (; ayraçlı) veya Excel dosyasından satırları okur."""
    yol = Path(yol)
    satirlar = []
    if yol.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(yol, read_only=True, data_only=True)
        ws = wb["Personel listesi"] if "Personel listesi" in wb.sheetnames else wb.active
        basliklar = None
        for i, r in enumerate(ws.iter_rows(values_only=True), start=1):
            hucreler = ["" if v is None else str(v).strip() for v in r]
            if basliklar is None:
                anahtar = [ad_anahtari(h) for h in hucreler]
                if "ad soyad" in anahtar:
                    basliklar = {a: j for j, a in enumerate(anahtar)}
                continue
            def al(*adlar):
                for a in adlar:
                    if a in basliklar:
                        return hucreler[basliklar[a]]
                return ""
            ad = al("ad soyad")
            if ad:
                satirlar.append(Satir(str(i), al("bolum", "personel bolumu"), al("sinif / rutbe / unvan"), ad, al("sicili", "sicil")))
        return satirlar
    with yol.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            satirlar.append(Satir(r["satir"], r["bolum"].strip(), r["sinif_rutbe_unvan"].strip(), r["ad_soyad"].strip(), r["sicil"].strip()))
    return satirlar


@dataclass
class Degisiklik:
    satir: Satir
    personel: Personel = None
    durum: str = ""             # eslesti, benzer, yeni, cozulemedi
    benzerlik: float = 0
    alanlar: dict = field(default_factory=dict)   # alan -> (eski, yeni)
    notlar: list = field(default_factory=list)
    sicil: str = ""


def planla(satirlar):
    """Satırları personelle eşleştirir, yapılacak değişiklikleri hesaplar (veritabanına yazmaz)."""
    rutbeler = {s.metin: s for s in Secenek.objects.filter(tur=Secenek.RUTBE)}
    siniflar = {s.metin: s for s in Secenek.objects.filter(tur=Secenek.SINIF)}
    unvanlar = {s.metin: s for s in Secenek.objects.filter(tur=Secenek.UNVAN)}
    bolumler = {ad_anahtari(b.ad): b for b in Bolum.objects.all()}
    personel = list(Personel.objects.select_related("rutbe", "sinif", "unvan", "bolum"))
    anahtarlar = {}
    for p in personel:
        anahtarlar.setdefault(ad_anahtari(p.ad_soyad), []).append(p)

    # aynı kişinin birden çok satırı: BES dışındaki satır asıl
    gruplar = {}
    for s in satirlar:
        gruplar.setdefault(ad_anahtari(s.ad), []).append(s)
    # 1. tur: adı birebir aynı olanlar; 2. tur: benzer ad, sadece 1. turda kimseyle eşleşmemiş personel arasında
    # (yoksa "Hasan Can KARTEL", listede ayrıca bulunan "Hasan Can KIRAÇ"ın kaydına yazılabilirdi)
    sonuc = []
    kullanilan = set()
    for anahtar, liste in gruplar.items():
        asil = next((s for s in liste if s.bolum != BES), liste[0])
        d = Degisiklik(satir=asil)
        if len(liste) > 1:
            d.notlar.append("Listede " + " ve ".join(s.bolum for s in liste) + " olarak geçiyor; asıl bölüm " + asil.bolum)
        adaylar = anahtarlar.get(anahtar, [])
        if len(adaylar) == 1:
            d.personel, d.durum, d.benzerlik = adaylar[0], "eslesti", 1
            kullanilan.add(adaylar[0].pk)
        elif len(adaylar) > 1:
            d.durum = "cozulemedi"
            d.notlar.append("Bu adla birden fazla personel var")
        d.sicil = next((s.sicil for s in liste if s.sicil not in BOS_SICIL), "")
        sonuc.append(d)
    bos = [p for p in personel if p.pk not in kullanilan]
    for d in sonuc:
        if d.durum:
            continue
        anahtar = ad_anahtari(d.satir.ad)
        en = max(((p, SequenceMatcher(None, anahtar, ad_anahtari(p.ad_soyad)).ratio()) for p in bos),
                 key=lambda x: x[1], default=(None, 0))
        if en[1] >= 0.9:
            d.personel, d.durum, d.benzerlik = en[0], "benzer", en[1]
            bos.remove(en[0])
            d.notlar.append(f"Ad tam eşleşmedi, en yakın: {en[0].ad_soyad} (%{round(en[1] * 100)})")
        else:
            d.durum = "yeni"

    for d in sonuc:
        asil = d.satir
        sicil = d.sicil
        a = ayristir(asil.sru, rutbeler)
        if a.cozulemeyen:
            d.notlar.append(f"Okunamayan kısım: \"{a.cozulemeyen}\"")
        hedef = {
            "rutbe": rutbeler.get(a.rutbe),
            "sinif": siniflar.get(a.sinif) if a.sinif else None,
            "unvan": unvanlar.get(a.unvan) if a.unvan else None,
            "bolum": bolumler.get(ad_anahtari(asil.bolum)),
            "sicil": sicil,
        }
        if a.sinif and a.sinif not in siniflar:
            hedef["sinif"] = ("YENİ", a.sinif)
        if asil.bolum and hedef["bolum"] is None:
            d.notlar.append(f"Bölüm bulunamadı: {asil.bolum}")
        for alan, yeni in hedef.items():
            eski = getattr(d.personel, alan) if d.personel else None
            if yeni in (None, "") or yeni == eski:
                continue
            d.alanlar[alan] = (eski, yeni)
    return sonuc


def uygula(plan, yeni_ekle=False):
    """Planı veritabanına yazar. Dönüş: (güncellenen, eklenen, yeni sınıf seçenekleri)."""
    guncel = eklenen = 0
    yeni_siniflar = {}
    for d in plan:
        if d.durum == "cozulemedi" or (d.durum == "yeni" and not yeni_ekle):
            continue
        p = d.personel or Personel(ad_soyad=d.satir.ad)
        for alan, (_, yeni) in d.alanlar.items():
            if isinstance(yeni, tuple):  # henüz olmayan sınıf seçeneği
                metin = yeni[1]
                if metin not in yeni_siniflar:
                    yeni_siniflar[metin], _ = Secenek.objects.get_or_create(tur=Secenek.SINIF, metin=metin)
                yeni = yeni_siniflar[metin]
            setattr(p, alan, yeni)
        if d.alanlar or p.pk is None:
            p.save()
            eklenen += d.personel is None
            guncel += d.personel is not None
    return guncel, eklenen, list(yeni_siniflar)
