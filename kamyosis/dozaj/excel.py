"""Öğretim programları Excel'inden okuma.

Beklenen düzen (Plan Program Kısmı'nın dosyası): her program ayrı sayfada; başlıkta "PROGRAM ADI : …"; dört yarıyıl
yan yana / alt alta bloklar halinde. Her blokta "DERS KODU" başlığı, yanında "1'İNCİ YARIYIL" ya da "I. YARIYIL",
sağında DS, T, U, L, KR, AKTS sütunları; dersler "TOPLAM" satırına kadar sürer. Sütun ve satır yerleri sabit
varsayılmaz, başlıklardan bulunur."""

import re

from .kurallar import buyuk

SAYI_BASLIKLARI = ("DS", "T", "U", "L", "KR", "AKTS")
ROMA = {"IV": 4, "III": 3, "II": 2, "I": 1}


class ExcelHatasi(Exception):
    pass


def _metin(v):
    return re.sub(r"\s+", " ", str(v)).strip() if v is not None else ""


def _sayi(v):
    if v is None or v == "":
        return 0
    try:
        return max(int(round(float(str(v).replace(",", ".")))), 0)
    except ValueError:
        return 0


def yariyil_no(metin):
    """"1'İNCİ YARIYIL" → 1, "III. YARIYIL" → 3, "II.YARIYIL" → 2. Tanınmazsa None."""
    m = buyuk(metin)
    if "YARIYIL" not in m:
        return None
    r = re.match(r"\s*([1-4])", m)
    if r:
        return int(r.group(1))
    r = re.match(r"\s*(IV|III|II|I)\b", m)
    return ROMA[r.group(1)] if r else None


def _sayfa_oku(ws):
    hucreler = {}
    for satir in ws.iter_rows():
        for h in satir:
            if h.value is not None:
                hucreler[(h.row, h.column)] = h.value
    program_adi = ""
    for v in hucreler.values():
        m = buyuk(_metin(v))
        if "PROGRAM ADI" in m and ":" in m:
            program_adi = m.split(":", 1)[1].replace("BÖLÜM BAŞKANLIĞI", "").strip()
            break
    dersler, uyarilar = [], []
    basliklar = [(r, c) for (r, c), v in hucreler.items() if buyuk(_metin(v)).replace(" ", "") == "DERSKODU"]
    for r, c in sorted(basliklar):
        yy = yariyil_no(_metin(hucreler.get((r, c + 1))))
        if yy is None:
            uyarilar.append(f"{r}. satırdaki blokta yarıyıl okunamadı.")
            continue
        sutun = {}
        for cc in range(c + 2, c + 16):
            ad = buyuk(_metin(hucreler.get((r, cc))))
            if ad in SAYI_BASLIKLARI and ad not in sutun:
                sutun[ad] = cc
        if "DS" not in sutun:
            uyarilar.append(f"{yy}. yarıyıl bloğunda DS sütunu bulunamadı.")
            continue
        for rr in range(r + 1, r + 40):
            ad = _metin(hucreler.get((rr, c + 1)))
            if "TOPLAM" in buyuk(ad):
                break
            kod = buyuk(_metin(hucreler.get((rr, c)))).replace(" ", "")
            if not kod:
                continue
            sayilar = {k: _sayi(hucreler.get((rr, sutun[k]))) if k in sutun else 0 for k in SAYI_BASLIKLARI}
            dersler.append({"yariyil": yy, "kod": kod, "ad": ad, "ds": sayilar["DS"], "t": sayilar["T"],
                            "u": sayilar["U"], "l": sayilar["L"], "kr": sayilar["KR"], "akts": sayilar["AKTS"]})
    return program_adi, dersler, uyarilar


def oku(dosya):
    """[{sayfa, program_adi, dersler: [...], uyarilar: [...]}] — ders bloğu olmayan sayfalar atlanır."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(dosya, data_only=True, read_only=False)
    except Exception as e:  # bozuk ya da Excel olmayan dosya
        raise ExcelHatasi("Dosya Excel (.xlsx) olarak açılamadı.") from e
    out = []
    for ws in wb.worksheets:
        program_adi, dersler, uyarilar = _sayfa_oku(ws)
        if dersler:
            out.append({"sayfa": ws.title, "program_adi": program_adi, "dersler": dersler, "uyarilar": uyarilar})
    if not out:
        raise ExcelHatasi("Dosyada \"DERS KODU\" başlıklı ders bloğu bulunamadı.")
    return out


def _sade(metin):
    m = buyuk(metin)
    for k in ("TEKNOLOJİSİ", "TEKNOLOJİLERİ", "TEKNJ.", "TEKN.", "PROGRAMI", "BÖLÜM BAŞKANLIĞI"):
        m = m.replace(k, " ")
    return re.sub(r"[^0-9A-ZÇĞİÖŞÜ]+", " ", m).split()


def eslestir(sayfa, programlar):
    """Sayfayı (adı ya da içindeki program adı) bir programla eşleştirir; bulunamazsa None."""
    adaylar = [sayfa["program_adi"], sayfa["sayfa"]]
    for aday in adaylar:
        kelimeler = _sade(aday)
        if not kelimeler:
            continue
        for p in programlar:
            if buyuk(aday).strip() in (buyuk(p.kod), buyuk(p.ad)):
                return p
        for p in programlar:
            pk = _sade(p.ad)
            if pk and (pk == kelimeler or pk[0] == kelimeler[0]):
                return p
    return None
