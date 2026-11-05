"""Kimlik okuma listesinin Excel'e yazılması ve Excel'den geri okunması.

Excel'de "Tür" sütunundan Personel / Öğrenci seçilir, dosya geri yüklenir; "Kayıt no" sütunu satırı listedeki
kayda bağlar (boşsa yeni satır eklenir). Başlıklar adlarından tanınır, sütun sırası değişse de okunur.
"""

import datetime
import io

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .models import KimlikKaydi
from .okuma import sade
from .servis import denetle

SUTUNLAR = [
    ("Kayıt no", "id", 9),
    ("Tür", "tur", 11),
    ("T.C. Kimlik No", "tc", 14),
    ("Soyadı", "soyad", 16),
    ("Adı", "ad", 18),
    ("Doğum Tarihi", "dogum_tarihi", 12),
    ("Cinsiyeti", "cinsiyet", 9),
    ("Seri No", "seri_no", 12),
    ("Uyruğu", "uyruk", 8),
    ("Son Geçerlilik", "son_gecerlilik", 12),
    ("Anne Adı", "anne_adi", 14),
    ("Baba Adı", "baba_adi", 14),
    ("Veren Makam", "veren_makam", 24),
    ("Uyarılar", "uyarilar", 50),
]
TUR_YAZI = dict(KimlikKaydi.TURLER)
CINSIYET_YAZI = dict(KimlikKaydi.CINSIYETLER)
TARIHLER = {"dogum_tarihi", "son_gecerlilik"}
SARI = PatternFill("solid", fgColor="FFF3C4")
EK_SATIR = 300  # açılır listeler, sonradan elle eklenecek satırları da kapsasın


def yaz(kayitlar):
    wb = Workbook()
    ws = wb.active
    ws.title = "Kimlikler"
    ws.append([b for b, _, _ in SUTUNLAR])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for k in kayitlar:
        satir = []
        for _, alan, _ in SUTUNLAR:
            d = getattr(k, alan)
            if alan == "tur":
                d = TUR_YAZI.get(d, "")
            elif alan == "cinsiyet":
                d = CINSIYET_YAZI.get(d, "")
            elif alan == "uyarilar":
                d = " · ".join(k.uyari_listesi)
            satir.append(d if d is not None else "")
        ws.append(satir)
        supheli = k.supheli_alanlar
        for i, (_, alan, _) in enumerate(SUTUNLAR, 1):
            c = ws.cell(row=ws.max_row, column=i)
            if alan in TARIHLER:
                c.number_format = "DD.MM.YYYY"
            elif alan in ("tc", "seri_no"):
                c.number_format = "@"
            if alan in supheli:
                c.fill = SARI
    son = len(kayitlar) + EK_SATIR
    tur = DataValidation(type="list", formula1='"Personel,Öğrenci"', allow_blank=True,
                         errorTitle="Tür", error="Personel ya da Öğrenci seçin.")
    cinsiyet = DataValidation(type="list", formula1='"Erkek,Kadın"', allow_blank=True)
    ws.add_data_validation(tur)
    ws.add_data_validation(cinsiyet)
    tur.add(f"B2:B{son}")
    cinsiyet.add(f"G2:G{son}")
    for i, (_, _, en) in enumerate(SUTUNLAR, 1):
        ws.column_dimensions[get_column_letter(i)].width = en
    for satir in range(2, son + 1):  # elle eklenecek satırlarda da T.C. no metin kalsın (baştaki 0 / bilimsel yazım)
        ws.cell(row=satir, column=3).number_format = "@"
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(SUTUNLAR))}{max(len(kayitlar) + 1, 2)}"
    tampon = io.BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


class ExcelHatasi(Exception):
    pass


def _baslik_anahtari(metin):
    return "".join(c for c in sade(metin) if c.isalnum())


_BASLIKLAR = {_baslik_anahtari(b): alan for b, alan, _ in SUTUNLAR}
_BASLIKLAR.update({"tckimlikno": "tc", "tcno": "tc", "kimlikno": "tc", "tc": "tc", "soyad": "soyad", "ad": "ad",
                   "cinsiyet": "cinsiyet", "uyruk": "uyruk", "dogumtarihi": "dogum_tarihi", "seri": "seri_no",
                   "serino": "seri_no", "songecerliliktarihi": "son_gecerlilik", "tip": "tur"})


def _metin(d):
    if d is None:
        return ""
    if isinstance(d, float) and d.is_integer():
        d = int(d)
    return " ".join(str(d).split())


def _tarih(d):
    if d in (None, ""):
        return None
    if isinstance(d, datetime.datetime):
        return d.date()
    if isinstance(d, datetime.date):
        return d
    s = _metin(d)
    for bicim in ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(s, bicim).date()
        except ValueError:
            pass
    raise ValueError(s)


def _tur(d):
    s = sade(_metin(d))
    if s.startswith("per"):
        return KimlikKaydi.PERSONEL
    if s.startswith("ogr"):
        return KimlikKaydi.OGRENCI
    return ""


def _cinsiyet(d):
    s = sade(_metin(d))
    if s in ("e", "erkek", "m", "male", "e/m"):
        return "E"
    if s in ("k", "kadin", "f", "female", "k/f"):
        return "K"
    return ""


def oku(dosya):
    """Excel satırlarını [(satır no, {alan: değer})] olarak döner; tarih okunamazsa ExcelHatasi."""
    try:
        wb = load_workbook(dosya, data_only=True, read_only=True)
    except Exception as e:  # bozuk / Excel olmayan dosya
        raise ExcelHatasi("Dosya Excel (.xlsx) olarak açılamadı.") from e
    ws = wb.worksheets[0]
    satirlar = ws.iter_rows(values_only=True)
    try:
        baslik = next(satirlar)
    except StopIteration:
        raise ExcelHatasi("Dosya boş.")
    sutunlar = {}
    for i, b in enumerate(baslik):
        alan = _BASLIKLAR.get(_baslik_anahtari(_metin(b)))
        if alan and alan not in sutunlar:
            sutunlar[alan] = i
    if "tc" not in sutunlar or not ({"ad", "soyad"} & sutunlar.keys()):
        raise ExcelHatasi("Başlık satırında en az “T.C. Kimlik No”, “Soyadı” ve “Adı” sütunları olmalı.")
    sonuc, hatalar = [], []
    for no, satir in enumerate(satirlar, start=2):
        degerler = {}
        for alan, i in sutunlar.items():
            d = satir[i] if i < len(satir) else None
            try:
                if alan in TARIHLER:
                    degerler[alan] = _tarih(d)
                elif alan == "tur":
                    degerler[alan] = _tur(d)
                elif alan == "cinsiyet":
                    degerler[alan] = _cinsiyet(d)
                elif alan == "id":
                    s = _metin(d)
                    degerler[alan] = int(s) if s.isdigit() else None
                elif alan == "tc":
                    degerler[alan] = _metin(d).replace(" ", "")[:11]
                elif alan != "uyarilar":
                    degerler[alan] = _metin(d)
            except ValueError as e:
                hatalar.append(f"{no}. satır: “{e}” tarih olarak okunamadı (gg.aa.yyyy yazın).")
        if not any(degerler.get(a) for a in ("tc", "ad", "soyad")):
            continue
        sonuc.append((no, degerler))
    wb.close()
    if hatalar:
        raise ExcelHatasi(" ".join(hatalar[:5]) + (" …" if len(hatalar) > 5 else ""))
    return sonuc


def ice_aktar(dosya, kullanici):
    """Excel'i listeye işler. Dönüş: (güncellenen, eklenen)."""
    satirlar = oku(dosya)
    idler = [d["id"] for _, d in satirlar if d.get("id")]
    mevcut = {k.pk: k for k in KimlikKaydi.objects.filter(pk__in=idler)}
    guncellenen = eklenen = 0
    for _, d in satirlar:
        k = mevcut.get(d.pop("id", None))
        if k is not None and k.aktarim:
            continue  # aktarılmış satır Excel'den değiştirilmez
        yeni = k is None
        if yeni:
            k = KimlikKaydi(ekleyen=kullanici, kaynak="excel")
        degisen = set()
        for alan, deger in d.items():
            if getattr(k, alan) != deger:
                setattr(k, alan, deger)
                degisen.add(alan)
        if yeni or degisen - {"tur"}:
            denetle(k)  # kimlik bilgisi elle düzeltildi: okuma uyarıları yerine kalıcı denetimler
        if yeni or degisen:
            k.save()
            eklenen += yeni
            guncellenen += not yeni
    return guncellenen, eklenen
