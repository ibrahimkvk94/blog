"""Sınav takvimi iş kuralları: yetki, Excel okuma/yazma, sayfa için gruplama ve denetimler."""

import datetime
import io
import re
from collections import Counter, OrderedDict, defaultdict

from django.db import transaction
from django.http import Http404
from django.utils import timezone

from core.yetki import DUZENLEME, birim_bul, etkin_yetki

from .models import Satir

BIRIM = "sinav-icrasi"  # Ölçme Değerlendirme › Sınav İcrası; sınav takvimi bu sayfanın ilk sekmesi
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
_TR_SIRA = str.maketrans({"Ç": "C~", "Ğ": "G~", "İ": "I~", "I": "I", "Ö": "O~", "Ş": "S~", "Ü": "U~"})
_ASCII = str.maketrans({"Ç": "C", "Ğ": "G", "İ": "I", "Ö": "O", "Ş": "S", "Ü": "U", "ç": "C", "ğ": "G", "ı": "I",
                        "i": "I", "ö": "O", "ş": "S", "ü": "U"})


class TakvimHatasi(Exception):
    pass


def duzenleyebilir(request):
    """Plan yükleyip yayınlayabilir mi? Sınav İcrası biriminde Düzenleme (üst birimden de gelir) ya da süper kullanıcı."""
    u = request.user
    if not u.is_authenticated:
        return False
    if u.is_superuser:
        return True
    try:
        return etkin_yetki(request, birim_bul(request, BIRIM))[0] >= DUZENLEME
    except Http404:
        return False


def tr_anahtar(metin):
    """Türkçe alfabe sırası (BİL < ELK < İNŞ < İŞL < UÇT …)."""
    return (metin or "").upper().translate(_TR_SIRA)


def _ascii(metin):
    return " ".join(str(metin or "").translate(_ASCII).upper().split())


_KUCUK = str.maketrans({"I": "ı", "İ": "i"})
_BUYUK = str.maketrans({"i": "İ", "ı": "I"})
_BAGLAC = {"ve", "ile", "veya", "ya", "da", "de"}


def tr_baslik(metin):
    """“İNGİLİZCE 3” → “İngilizce 3”, “HAREKÂTIN UNSURLARI VE YÖNETİMİ” → “Harekâtın Unsurları ve Yönetimi”."""
    kelimeler = []
    for i, k in enumerate(str(metin or "").split()):
        k = k.translate(_KUCUK).lower()
        if i == 0 or k not in _BAGLAC:
            k = k[:1].translate(_BUYUK).upper() + k[1:]
        kelimeler.append(k)
    return " ".join(kelimeler)


def tur_duzelt(tur):
    tur = " ".join(str(tur or "").split())
    return re.sub(r"\s*\+\s*", " + ", tur)


def tur_sinifi(tur):
    """Rozet rengi: uygulama içeren, çoktan seçmeli, merkezî test (MT) ya da diğer."""
    t = _ascii(tur)
    if "UYG" in t:
        return "uyg"
    if "CS" in t.replace("Ç", "C"):
        return "cs"
    if "MT" in t:
        return "mt"
    return "diger"


def tarih_metni(t, gun=True):
    s = f"{t.day} {AYLAR[t.month - 1]} {t.year}"
    return f"{s} {GUNLER[t.weekday()]}" if gun else s


def saat_metni(bas, bit):
    return f"{bas:%H.%M}–{bit:%H.%M}" if bit else f"{bas:%H.%M}"


# ---------------------------------------------------------------- Excel'den okuma

_TARIH_RE = re.compile(r"(\d{1,2})\s*[./\- ]\s*([A-Za-zÇĞİÖŞÜçğıöşü]+|\d{1,2})\s*[./\- ]\s*(\d{4})")
_SAAT_RE = re.compile(r"(\d{1,2})[.:](\d{2})\s*(?:[-–—]\s*(\d{1,2})[.:](\d{2}))?")
_AY_ASCII = {_ascii(a): i + 1 for i, a in enumerate(AYLAR)}


def _tarih(deger):
    if isinstance(deger, datetime.datetime):
        return deger.date()
    if isinstance(deger, datetime.date):
        return deger
    m = _TARIH_RE.search(str(deger or ""))
    if not m:
        return None
    gun, ay, yil = m.groups()
    ay_no = int(ay) if ay.isdigit() else _AY_ASCII.get(_ascii(ay))
    try:
        return datetime.date(int(yil), ay_no, int(gun)) if ay_no else None
    except ValueError:
        return None


def _saat(deger):
    if isinstance(deger, datetime.time):
        return deger, None
    if isinstance(deger, datetime.datetime):
        return deger.time(), None
    m = _SAAT_RE.search(str(deger or ""))
    if not m:
        return None, None
    a, b, c, d = m.groups()
    try:
        bas = datetime.time(int(a), int(b))
        bit = datetime.time(int(c), int(d)) if c else None
    except ValueError:
        return None, None
    return bas, bit


def _sutun_turu(baslik):
    b = _ascii(baslik)
    if not b:
        return None
    if "TARIH" in b:
        return "tarih"
    if "SAAT" in b:
        return "saat"
    if "KOD" in b:
        return "kod"
    if "DERS" in b:
        return "ders"
    if "SINIF" in b:
        return "sinif"
    if "BOLUM" in b or "PROGRAM" in b:
        return "bolum"
    if "TUR" in b:
        return "tur"
    return None


def excel_oku(dosya):
    """Okulun sınav planı Excel'i: başlık satırında SINAV TARİHİ, SINAV SAATİ, SINIF, DERS ADI, KOD, BÖLÜM/PROGRAM,
    SINAV TÜRÜ sütunları aranır (sıra ve fazladan sütun önemli değil). Birleştirilmiş tarih/saat hücreleri aşağı doğru
    doldurulur. Döner: (başlıktan ad, satır sözlükleri, uyarılar)."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(dosya, data_only=True, read_only=False)
    except Exception as e:  # bozuk / Excel olmayan dosya
        raise TakvimHatasi("Dosya Excel (.xlsx / .xlsm) olarak açılamadı.") from e
    for ws in wb.worksheets:
        bulundu = _sayfa_oku(ws)
        if bulundu is not None:
            return bulundu
    raise TakvimHatasi("Başlık satırı bulunamadı: sütunlarda “SINAV TARİHİ” ve “DERS ADI” olmalı.")


def _sayfa_oku(ws):
    satirlar = list(ws.iter_rows(values_only=True))
    bas_satir, sutunlar = None, {}
    for i, r in enumerate(satirlar[:20]):
        turler = {}
        for j, v in enumerate(r):
            t = _sutun_turu(v)
            if t and t not in turler:
                turler[t] = j
        if "tarih" in turler and "ders" in turler:
            bas_satir, sutunlar = i, turler
            break
    if bas_satir is None:
        return None
    ad = " ".join(" ".join(str(v).split()) for r in satirlar[:bas_satir] for v in r if v not in (None, ""))
    out, uyarilar = [], []
    tarih = bas = bit = None
    for i, r in enumerate(satirlar[bas_satir + 1:], start=bas_satir + 2):
        def al(t):
            j = sutunlar.get(t)
            return r[j] if j is not None and j < len(r) else None

        if al("tarih") not in (None, ""):
            yeni = _tarih(al("tarih"))
            if yeni is None:
                uyarilar.append(f"{i}. satır: tarih okunamadı ({al('tarih')}).")
            else:
                tarih = yeni
        if al("saat") not in (None, ""):
            b1, b2 = _saat(al("saat"))
            if b1 is None:
                uyarilar.append(f"{i}. satır: saat okunamadı ({al('saat')}).")
            else:
                bas, bit = b1, b2
        ders = " ".join(str(al("ders") or "").split())
        if not ders:
            continue
        if tarih is None or bas is None:
            uyarilar.append(f"{i}. satır ({ders}): tarih ya da saat yok, alınmadı.")
            continue
        sinif = al("sinif")
        try:
            sinif = int(float(sinif)) if sinif not in (None, "") else None
        except (TypeError, ValueError):
            m = re.search(r"\d", str(sinif))
            sinif = int(m.group()) if m else None
        out.append({"tarih": tarih, "baslangic": bas, "bitis": bit, "sinif": sinif, "ders": ders,
                    "kod": " ".join(str(al("kod") or "").split()), "bolum": " ".join(str(al("bolum") or "").split()),
                    "tur": tur_duzelt(al("tur"))})
    if not out:
        return None
    return ad, out, uyarilar


@transaction.atomic
def satirlari_yaz(takvim, satirlar):
    takvim.satirlar.all().delete()
    Satir.objects.bulk_create([Satir(takvim=takvim, sira=i, **{k: s[k] for k in (
        "tarih", "baslangic", "bitis", "sinif", "ders", "kod", "bolum", "tur")}) for i, s in enumerate(satirlar)])
    takvim.save(update_fields=["guncelleme"])


# ---------------------------------------------------------------- sayfa verisi

def ozet(takvim):
    satirlar = list(takvim.satirlar.all())
    gunler = sorted({s.tarih for s in satirlar})
    return {"satir": len(satirlar), "sinav": len({(s.tarih, s.baslangic, s.kod, s.ders) for s in satirlar}),
            "gun": len(gunler), "ilk": gunler[0] if gunler else None, "son": gunler[-1] if gunler else None,
            "program": len({s.bolum for s in satirlar if s.bolum})}


def cakismalar(satirlar):
    """Aynı program ve sınıfın aynı oturumda birden çok sınavı."""
    c = defaultdict(list)
    for s in satirlar:
        if s.bolum:
            c[(s.tarih, s.baslangic, s.bolum, s.sinif)].append(s)
    return [v for v in c.values() if len(v) > 1]


def sayfa_verisi(takvim, bolum_adlari=None):
    bolum_adlari = bolum_adlari or {}
    satirlar = list(takvim.satirlar.all())
    bugun = timezone.localdate()
    cakisan_idler = {s.pk for grup in cakismalar(satirlar) for s in grup}

    # Günler › oturumlar › sınavlar (aynı ders birden çok programda tek kart)
    gunler = OrderedDict()
    for s in satirlar:
        gun = gunler.setdefault(s.tarih, OrderedDict())
        oturum = gun.setdefault((s.baslangic, s.bitis), OrderedDict())
        anahtar = (s.sinif, s.ders, s.kod, s.tur)
        kart = oturum.setdefault(anahtar, {"sinif": s.sinif, "ders": s.ders, "kod": s.kod, "tur": s.tur,
                                           "ad": tr_baslik(s.ders), "tur_sinifi": tur_sinifi(s.tur), "bolumler": [],
                                           "cakisma": False})
        if s.bolum and s.bolum not in kart["bolumler"]:
            kart["bolumler"].append(s.bolum)
        kart["cakisma"] = kart["cakisma"] or s.pk in cakisan_idler
    # Oturum yuvaları (ör. 08.45, 10.30, 14.15, 15.45): günler aynı sütunlarda hizalanır
    yuvalar = sorted({(s.baslangic, s.bitis) for s in satirlar}, key=lambda x: (x[0], x[1] or x[0]))
    gun_listesi = []
    for tarih, oturumlar in gunler.items():
        ot = []
        for (bas, bit), kartlar in oturumlar.items():
            kartlar = list(kartlar.values())
            for k in kartlar:
                k["bolumler"].sort(key=tr_anahtar)
                k["ara"] = " ".join([k["ders"], k["kod"], *k["bolumler"]]).lower()
            siniflar = sorted({k["sinif"] for k in kartlar if k["sinif"]})
            ot.append({"bas": bas, "bit": bit, "saat": saat_metni(bas, bit), "kartlar": kartlar, "siniflar": siniflar,
                       "sinav_sayisi": len(kartlar)})
        sozluk = {(o["bas"], o["bit"]): o for o in ot}
        gun_listesi.append({"tarih": tarih, "gun_no": tarih.day, "ay": AYLAR[tarih.month - 1],
                            "yuvalar": [sozluk.get(y) or {"bos": True, "saat": saat_metni(*y)} for y in yuvalar],
                            "sinav_sayisi": sum(o["sinav_sayisi"] for o in ot),
                            "gun_adi": GUNLER[tarih.weekday()], "bugun": tarih == bugun,
                            "yarin": tarih == bugun + datetime.timedelta(days=1), "gecti": tarih < bugun,
                            "oturumlar": ot})

    # Program tablosu: satırlar program × sınıf, sütunlar gün › oturum
    sutunlar = [(g["tarih"], o["bas"]) for g in gun_listesi for o in g["oturumlar"]]
    gun_ilk = {i for i, (t, _b) in enumerate(sutunlar) if i == 0 or sutunlar[i - 1][0] != t}
    gun_basliklari = [{"g": g, "genislik": len(g["oturumlar"])} for g in gun_listesi]
    hucreler = defaultdict(list)
    for s in satirlar:
        hucreler[(s.bolum, s.sinif, s.tarih, s.baslangic)].append(s)
    programlar = sorted({s.bolum for s in satirlar if s.bolum}, key=tr_anahtar)
    siniflar = sorted({s.sinif for s in satirlar if s.sinif})
    tablo = []
    for b in programlar:
        for sn in siniflar:
            if not any(k[0] == b and k[1] == sn for k in hucreler):
                continue
            satir_hucreleri = []
            for i, (t, bas) in enumerate(sutunlar):
                sinavlar = hucreler.get((b, sn, t, bas), [])
                satir_hucreleri.append({"sinavlar": [{"kod": x.kod, "ders": x.ders, "tur": x.tur,
                                                      "ad": tr_baslik(x.ders), "tur_sinifi": tur_sinifi(x.tur)} for x in sinavlar],
                                        "cakisma": len(sinavlar) > 1, "gecti": t < bugun, "bugun": t == bugun,
                                        "gun_ilk": i in gun_ilk})
            tablo.append({"bolum": b, "bolum_adi": bolum_adlari.get(b, b), "sinif": sn, "hucreler": satir_hucreleri,
                          "sayi": sum(len(h["sinavlar"]) for h in satir_hucreleri)})
    oturum_basliklari = [{"saat": o["saat"], "bas": o["bas"], "gun": g, "gun_ilk": i == 0}
                         for g in gun_listesi for i, o in enumerate(g["oturumlar"])]

    kalan = None
    if gun_listesi:
        ilk, son = gun_listesi[0]["tarih"], gun_listesi[-1]["tarih"]
        if bugun < ilk:
            kalan = {"durum": "once", "gun": (ilk - bugun).days}
        elif bugun <= son:
            kalan = {"durum": "suruyor", "bugun_var": any(g["bugun"] for g in gun_listesi)}
        else:
            kalan = {"durum": "bitti"}
    turler = Counter(tur_sinifi(s.tur) for s in satirlar)
    return {"gunler": gun_listesi, "programlar": [{"kod": b, "ad": bolum_adlari.get(b, b)} for b in programlar],
            "siniflar": siniflar, "tablo": tablo, "gun_basliklari": gun_basliklari,
            "oturum_basliklari": oturum_basliklari, "kalan": kalan, "turler": turler,
            "cakismalar": [sorted(g, key=lambda x: x.kod) for g in cakismalar(satirlar)]}


# ---------------------------------------------------------------- Excel'e yazma

def excel_yaz(takvim):
    """Planı okulun Excel düzeninde verir: tarih ve saat hücreleri birleştirilmiş, Times New Roman 12."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Sınav Planı"
    yazi = Font(name="Times New Roman", size=12)
    kalin = Font(name="Times New Roman", size=12, bold=True)
    ince = Side(style="thin", color="000000")
    cerceve = Border(left=ince, right=ince, top=ince, bottom=ince)
    orta = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sol = Alignment(horizontal="left", vertical="center", wrap_text=True)
    basliklar = ["SINAV TARİHİ", "SINAV SAATİ", "SINIF", "DERS ADI", "ÖLÇME SİSTEMİ KODLARI", "BÖLÜM / PROGRAM",
                 "SINAV TÜRÜ"]
    genislik = [20, 15, 8, 52, 16, 14, 22]
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(basliklar))
    ws.cell(1, 1, takvim.ad.upper()).font = Font(name="Times New Roman", size=13, bold=True)
    ws.cell(1, 1).alignment = orta
    ws.row_dimensions[1].height = 34
    gri = PatternFill("solid", fgColor="D9D9D9")
    for j, b in enumerate(basliklar, start=1):
        c = ws.cell(2, j, b)
        c.font, c.alignment, c.border, c.fill = kalin, orta, cerceve, gri
        ws.column_dimensions[get_column_letter(j)].width = genislik[j - 1]
    satirlar = list(takvim.satirlar.all())
    r = 3
    for s in satirlar:
        degerler = [tarih_metni(s.tarih).replace(" " + GUNLER[s.tarih.weekday()], "\n" + GUNLER[s.tarih.weekday()]),
                    saat_metni(s.baslangic, s.bitis).replace("–", "-"), s.sinif, s.ders, s.kod, s.bolum, s.tur]
        for j, v in enumerate(degerler, start=1):
            c = ws.cell(r, j, v)
            c.font, c.border, c.alignment = yazi, cerceve, (sol if j == 4 else orta)
        r += 1

    def birlestir(sutun, anahtar):
        i = 0
        while i < len(satirlar):
            k = i
            while k + 1 < len(satirlar) and anahtar(satirlar[k + 1]) == anahtar(satirlar[i]):
                k += 1
            if k > i:
                ws.merge_cells(start_row=i + 3, start_column=sutun, end_row=k + 3, end_column=sutun)
            i = k + 1

    birlestir(1, lambda s: s.tarih)
    birlestir(2, lambda s: (s.tarih, s.baslangic))
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:G{max(r - 1, 2)}"
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
