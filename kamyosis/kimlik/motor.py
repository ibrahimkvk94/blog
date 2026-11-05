"""Tesseract yazı okuma motoru: fotoğrafı hazırlar, motoru bu bilgisayarda çalıştırır, `okuma` kurallarına verir.

Fotoğraf diske yazılmaz; motorun girişine bellekten (stdin) verilir. İnternet bağlantısı gerekmez.

Kurulum (bir kez, yönetici olarak): UB Mannheim Tesseract Windows kurulumu, "Additional language data" altında
Turkish seçilerek. Yol farklıysa ayarlarda TESSERACT_YOLU verilir.
"""

import io
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

from . import okuma

VARSAYILAN_YOLLAR = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
MRZ_HARFLERI = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"


class MotorYok(Exception):
    """Tesseract kurulu değil ya da çalışmıyor."""


def yol():
    adaylar = [getattr(settings, "TESSERACT_YOLU", "")] + VARSAYILAN_YOLLAR + [shutil.which("tesseract") or ""]
    for a in adaylar:
        if a and Path(a).is_file():
            return a
    raise MotorYok("Yazı okuma motoru (Tesseract) bu bilgisayarda bulunamadı.")


def _calistir(img, *args, zaman=90):
    tampon = io.BytesIO()
    img.save(tampon, format="PNG")
    try:
        r = subprocess.run([yol(), "stdin", "stdout", *args], input=tampon.getvalue(), capture_output=True,
                           timeout=zaman, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise MotorYok(f"Yazı okuma motoru çalıştırılamadı: {e}") from e
    if r.returncode != 0:
        raise MotorYok("Yazı okuma motoru hata verdi: " + r.stderr.decode("utf-8", "replace")[-300:])
    return r.stdout.decode("utf-8", "replace")


_DILLER = None


def diller():
    global _DILLER
    if _DILLER is None:
        try:
            r = subprocess.run([yol(), "--list-langs"], capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as e:
            raise MotorYok(f"Yazı okuma motoru çalıştırılamadı: {e}") from e
        cikti = (r.stdout or r.stderr).decode("utf-8", "replace").splitlines()
        _DILLER = {s.strip() for s in cikti[1:] if s.strip()}
    return _DILLER


def durum():
    """(hazır mı, açıklama) — sayfada gösterilir."""
    try:
        d = diller()
    except MotorYok as e:
        return False, str(e)
    if "tur" not in d:
        return True, "Yazı okuma motoru kurulu, ancak Türkçe dil paketi yok: Ç, Ğ, İ, Ö, Ş, Ü harfleri yanlış okunabilir."
    return True, "Yazı okuma motoru hazır."


def hazirla(dosya):
    """Fotoğrafı açar, telefonun döndürme bilgisine göre çevirir, gri tona alır, okunur boyuta getirir."""
    img = Image.open(dosya)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    uzun = max(img.size)
    if uzun > 2600:
        img.thumbnail((2600, 2600), Image.LANCZOS)
    elif uzun < 1600:
        oran = 1600 / uzun
        img = img.resize((round(img.width * oran), round(img.height * oran)), Image.LANCZOS)
    return ImageOps.autocontrast(img, cutoff=1)


def parcalar(img):
    """Seyrek metin kipinde (psm 11) satırları ve kutularını döner."""
    dil = "tur+eng" if "tur" in diller() else "eng"
    tsv = _calistir(img, "-l", dil, "--psm", "11", "tsv")
    satirlar = {}
    for s in tsv.splitlines()[1:]:
        p = s.split("\t")
        if len(p) < 12 or p[0] != "5" or not p[11].strip():
            continue
        try:
            if float(p[10]) < 0:
                continue
            sol, ust, en, boy = (int(x) for x in p[6:10])
        except ValueError:
            continue
        anahtar = (p[2], p[3], p[4])
        if anahtar not in satirlar:
            satirlar[anahtar] = okuma.Parca(p[11], sol, ust, sol + en, ust + boy)
        else:
            x = satirlar[anahtar]
            x.metin += " " + p[11]
            x.sol, x.ust, x.sag, x.alt = min(x.sol, sol), min(x.ust, ust), max(x.sag, sol + en), max(x.alt, ust + boy)
    return sorted(satirlar.values(), key=lambda x: (x.ust, x.sol))


def mrz_metinleri(img):
    """Arka yüzün alt yarısında yalnız MRZ harfleriyle (A-Z, 0-9, <) blok okuma; bulunamazsa tüm yüz."""
    metinler = []
    alt = img.crop((0, img.height // 2, img.width, img.height))
    for parca in (alt, img):
        metin = _calistir(parca, "-l", "eng", "--psm", "6", "-c", f"tessedit_char_whitelist={MRZ_HARFLERI}")
        metinler = [s for s in metin.splitlines() if s.strip()]
        if okuma.mrz_bul(metinler):
            break
    return metinler


def oku(on=None, arka=None):
    """Yüklenen ön / arka yüz dosyalarını okur; okuma.Sonuc döner."""
    on_p = parcalar(hazirla(on)) if on else []
    arka_p, mrz = [], []
    if arka:
        img = hazirla(arka)
        arka_p = parcalar(img)
        mrz = mrz_metinleri(img)
    return okuma.birlestir(on_p, arka_p, mrz)
