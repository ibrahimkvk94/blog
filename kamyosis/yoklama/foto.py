"""Personel fotoğrafı: yükleme (tek / zip ile toplu) ve küçültme.

- Dosya gerçekten resim mi diye Pillow ile açılarak denetlenir; telefon fotoğrafının yönü düzeltilir, EXIF (konum vb.)
  atılır, en uzun kenar 600 piksele indirilip JPEG olarak kaydedilir. Eski fotoğraf silinir.
- Toplu yükleme: zip içindeki dosya adı (uzantısız) personelin sicil numarası ya da T.C. kimlik numarası olmalı.
  Eşleştirme yalnızca bellekte yapılır; T.C. kimlik numarası hiçbir yere yazılmaz.
"""

import io
import secrets
import zipfile
from pathlib import PurePosixPath

from django.core.files.base import ContentFile

EN_BUYUK_KENAR = 600
EN_BUYUK_DOSYA = 15 * 1024 * 1024        # tek resim
EN_BUYUK_ZIP_ACIK = 300 * 1024 * 1024    # zip içi toplam (açılmış)
UZANTILAR = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}


class FotoHatasi(Exception):
    pass


def _islenmis(veri):
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(veri)) as resim:
            resim.load()
            resim = ImageOps.exif_transpose(resim)
            if resim.mode not in ("RGB", "L"):
                zemin = Image.new("RGB", resim.size, (255, 255, 255))
                if resim.mode in ("RGBA", "LA") or "transparency" in resim.info:
                    resim = resim.convert("RGBA")
                    zemin.paste(resim, mask=resim.split()[-1])
                else:
                    zemin.paste(resim.convert("RGB"))
                resim = zemin
            resim.thumbnail((EN_BUYUK_KENAR, EN_BUYUK_KENAR))
            cikti = io.BytesIO()
            resim.convert("RGB").save(cikti, "JPEG", quality=85, optimize=True)
            return cikti.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        raise FotoHatasi("Dosya okunabilir bir resim değil.") from e


def kaydet(personel, veri):
    """Fotoğrafı işleyip personele yazar (eskisini siler)."""
    if len(veri) > EN_BUYUK_DOSYA:
        raise FotoHatasi("Fotoğraf en fazla 15 MB olabilir.")
    jpeg = _islenmis(veri)
    eski = personel.fotograf.name if personel.fotograf else None
    personel.fotograf.save(f"{personel.pk}_{secrets.token_hex(4)}.jpg", ContentFile(jpeg), save=False)
    personel.save(update_fields=["fotograf"])
    if eski:
        personel.fotograf.storage.delete(eski)


def kaldir(personel):
    if personel.fotograf:
        ad = personel.fotograf.name
        personel.fotograf = ""
        personel.save(update_fields=["fotograf"])
        personel.fotograf.storage.delete(ad)


def _anahtar(metin):
    return "".join(ch for ch in str(metin or "") if ch.isalnum()).casefold()


def toplu(dosya, personeller):
    """Zip'ten toplu yükleme. Dönüş: (yüklenen adlar, eşleşmeyen dosyalar, hatalı dosyalar)."""
    sicil, tc = {}, {}
    for p in personeller:
        if p.sicil:
            sicil.setdefault(_anahtar(p.sicil), []).append(p)
        if p.personel_kodu:
            tc.setdefault(_anahtar(p.personel_kodu), []).append(p)
    try:
        arsiv = zipfile.ZipFile(dosya)
    except zipfile.BadZipFile as e:
        raise FotoHatasi("Dosya zip arşivi değil.") from e
    bilgiler = [b for b in arsiv.infolist() if not b.is_dir()]
    if sum(b.file_size for b in bilgiler) > EN_BUYUK_ZIP_ACIK:
        raise FotoHatasi("Zip içindeki dosyalar toplamı 300 MB'ı aşıyor; parça parça yükleyin.")
    yuklenen, eslesmeyen, hatali = [], [], []
    for b in bilgiler:
        yol = PurePosixPath(b.filename.replace("\\", "/"))
        if yol.name.startswith(".") or "__MACOSX" in yol.parts or yol.suffix.lower() not in UZANTILAR:
            continue
        anahtar = _anahtar(yol.stem)
        adaylar = sicil.get(anahtar) or tc.get(anahtar) or []
        if len(adaylar) != 1:
            eslesmeyen.append(yol.name)
            continue
        if b.file_size > EN_BUYUK_DOSYA:
            hatali.append(f"{yol.name} (15 MB'tan büyük)")
            continue
        try:
            kaydet(adaylar[0], arsiv.read(b))
        except FotoHatasi as e:
            hatali.append(f"{yol.name} ({e})")
            continue
        yuklenen.append(adaylar[0].ad_soyad)
    return yuklenen, eslesmeyen, hatali
