"""Tesseract yazı okuma motoru: fotoğrafı hazırlar, motoru bu bilgisayarda çalıştırır, `okuma` kurallarına verir.

Fotoğraf diske yazılmaz; motorun girişine bellekten (stdin) verilir. İnternet bağlantısı gerekmez.

Kurulum (bir kez, yönetici olarak): UB Mannheim Tesseract Windows kurulumu, "Additional language data" altında
Turkish seçilerek. Yol farklıysa ayarlarda TESSERACT_YOLU verilir.
"""

import io
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

from . import okuma

VARSAYILAN_YOLLAR = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
MRZ_HARFLERI = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
# Okuma işlemciyi yoğun kullanır: aynı anda en çok bu kadar okuma (sunucunun diğer sayfaları yavaşlamasın)
_SIRA = threading.BoundedSemaphore(getattr(settings, "KIMLIK_ESZAMANLI_OKUMA", 2))


class MotorYok(Exception):
    """Tesseract kurulu değil ya da çalışmıyor."""


class Mesgul(Exception):
    """Okuma sırası dolu."""


@contextmanager
def sira(bekleme):
    if not _SIRA.acquire(timeout=bekleme):
        raise Mesgul("Okuma sunucusu şu an meşgul.")
    try:
        yield
    finally:
        _SIRA.release()


def hizli_kontrol(dosya, yuz):
    """Canlı kameradan gelen karenin okunmaya hazır olup olmadığı: (uygun, mesaj).
    Ön yüzde T.C. no'nun kontrol haneleri, arka yüzde kod satırlarının kontrol haneleri tutmalı."""
    img = hazirla(dosya)
    if yuz == "arka":
        satirlar = okuma.mrz_bul(mrz_metinleri(img))
        if not satirlar:
            return False, "Arka yüzdeki 3 satırlık kod aranıyor; kartı çerçeveye oturtun."
        if okuma.mrz_puani(okuma.mrz_coz(satirlar)) >= 5:
            return True, "Arka yüz okundu."
        return False, "Kod satırları görüldü, netleşmesini bekliyorum…"
    b = okuma.on_yuz(parcalar(img))
    if b.get("tc"):
        return True, "Ön yüz okundu."
    if b.get("tc_ham") or b.get("soyad") or b.get("dogum_tarihi"):
        return False, "Kart görüldü, netleşmesini bekliyorum…"
    return False, "Kartın ön yüzünü çerçeveye oturtun."


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
    img = ImageOps.autocontrast(img, cutoff=1)
    aci = egim(img)
    if abs(aci) >= 0.5:
        img = img.rotate(aci, resample=Image.BICUBIC, expand=True, fillcolor=255)
    return img


def egim(img, sinir=12.0, adim=0.5):
    """Küçük eğimi (±12°) bulur: koyu noktaların satır toplamları en keskin olduğu açı. Dönüş: düzeltme açısı."""
    import numpy as np

    kucuk = img.copy()
    kucuk.thumbnail((900, 900))
    dizi = np.asarray(kucuk, dtype=np.float32)
    esik = dizi.mean() - dizi.std() * 0.5
    murekkep = Image.fromarray(((dizi < esik) * 255).astype(np.uint8))

    def puan(aci):
        satirlar = np.asarray(murekkep.rotate(aci, resample=Image.NEAREST, expand=True), dtype=np.float32).sum(axis=1)
        return float(np.square(np.diff(satirlar)).sum())

    kaba = max(np.arange(-sinir, sinir + 0.01, adim * 2), key=puan)
    return float(max(np.arange(kaba - adim * 2, kaba + adim * 2 + 0.01, adim / 2), key=puan))


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
    """Yalnız MRZ harfleriyle (A-Z, 0-9, <) blok okuma: önce alt yarı, sonra tüm yüz. Satırların hepsi döner;
    hangi birleşimin kontrol hanelerini tuttuğuna okuma.mrz_bul karar verir. Hepsi tutarsa ikinci okuma yapılmaz."""
    metinler = []
    alt = img.crop((0, img.height // 2, img.width, img.height))
    for parca in (alt, img):
        metin = _calistir(parca, "-l", "eng", "--psm", "6", "-c", f"tessedit_char_whitelist={MRZ_HARFLERI}")
        metinler += [s for s in metin.splitlines() if s.strip()]
        satirlar = okuma.mrz_bul(metinler)
        if satirlar and okuma.mrz_puani(okuma.mrz_coz(satirlar)) >= 6:
            break
    return metinler


def bolgeler(img, parcalar_, alanlar):
    """Etiketlerin altındaki değer bölgelerini kesip ayrıca okur: {alan: metin}."""
    dil = "tur+eng" if "tur" in diller() else "eng"
    sonuc = {}
    for alan in alanlar:
        et = okuma.etiket_bul(parcalar_, alan)
        if et is None:
            continue
        sol, ust, sag, alt = (round(x) for x in okuma.deger_kutusu(et, parcalar_))
        sag, alt = min(sag, img.width), min(alt, img.height)
        if sag - sol < 20 or alt - ust < 10:
            continue
        # Etiket kutusu değere binebilir (parantez, Ü/İ noktaları için bırakılan pay): kesit blok olarak okunur,
        # etiket olmayan geçerli son satır alınır.
        satirlar = _calistir(img.crop((sol, ust, sag, alt)), "-l", dil, "--psm", "6").splitlines()
        for satir in reversed([x.strip() for x in satirlar if x.strip()]):
            if not okuma._etiket_mi(okuma.Parca(satir)) and okuma.deger_sec(alan, satir):
                sonuc[alan] = satir
                break
    return sonuc


def _yonler(img):
    """Kart düz, ters ya da yan çekilmiş olabilir. Motorun yön tahmini kimlik kartında güvenilmez çıktı (kod satırı
    yazı tipi), bu yüzden yönler sırayla denenir; okuma tutunca durulur."""
    yield img
    for aci in (180, 90, 270):
        yield img.rotate(aci, expand=True)


def oku(on=None, arka=None):
    """Yüklenen ön / arka yüz dosyalarını okur; okuma.Sonuc döner."""
    on_p, arka_p, mrz, bolge = [], [], [], {}
    if on:
        ilk = hazirla(on)
        img, on_p = ilk, None
        for aday in _yonler(ilk):
            p = parcalar(aday)
            if on_p is None:
                on_p = p
            if okuma.on_yuz(p).get("tc"):
                img, on_p = aday, p
                break
        bolge.update(bolgeler(img, on_p, ["soyad", "ad"]))
    if arka:
        ilk = hazirla(arka)
        img, mrz = ilk, None
        for aday in _yonler(ilk):
            m = mrz_metinleri(aday)
            if mrz is None:
                mrz = m
            if okuma.mrz_bul(m):
                img, mrz = aday, m
                break
        arka_p = parcalar(img)
        bolge.update(bolgeler(img, arka_p, ["anne_adi", "baba_adi", "veren_makam"]))
    return okuma.birlestir(on_p, arka_p, mrz, bolge)
