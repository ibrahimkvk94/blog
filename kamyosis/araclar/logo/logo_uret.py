"""logo_kaynak.jpg (beyaz zeminli) → şeffaf zeminli logo sürümleri.

    .venv\\Scripts\\python.exe araclar\\logo\\logo_uret.py

Üretilenler (static/img): logo_siyah.png, logo_beyaz.png (açık/koyu zeminler için), favicon.png, favicon.ico
"""

from pathlib import Path

from PIL import Image, ImageOps

KLASOR = Path(__file__).resolve().parent
HEDEF = KLASOR.parents[1] / "static" / "img"
ESIK_ACIK, ESIK_KOYU = 235, 40  # bu değerden açık pikseller tamamen şeffaf, koyular tamamen opak


def alfa_maskesi(gri):
    """Parlaklıktan şeffaflık: beyaz → 0, siyah → 255; JPEG gürültüsü kırpılır."""
    def donustur(v):
        if v >= ESIK_ACIK:
            return 0
        if v <= ESIK_KOYU:
            return 255
        return round((ESIK_ACIK - v) * 255 / (ESIK_ACIK - ESIK_KOYU))
    return gri.point(donustur)


def renkli(alfa, renk):
    img = Image.new("RGBA", alfa.size, renk + (0,))
    img.putalpha(alfa)
    return img


def main():
    HEDEF.mkdir(parents=True, exist_ok=True)
    gri = ImageOps.grayscale(Image.open(KLASOR / "logo_kaynak.jpg"))
    alfa = alfa_maskesi(gri)
    kutu = alfa.point(lambda v: 255 if v > 30 else 0).getbbox()
    alfa = alfa.crop(kutu)
    # kenarlarda biraz boşluk, kare tuval
    kenar = max(alfa.size)
    pay = round(kenar * 0.04)
    kare = Image.new("L", (kenar + 2 * pay, kenar + 2 * pay), 0)
    kare.paste(alfa, ((kare.width - alfa.width) // 2, (kare.height - alfa.height) // 2))

    renkli(kare, (17, 24, 39)).save(HEDEF / "logo_siyah.png", optimize=True)
    renkli(kare, (255, 255, 255)).save(HEDEF / "logo_beyaz.png", optimize=True)

    # favicon: lacivert yuvarlak kare üstünde beyaz logo
    boyut = 256
    zemin = Image.new("RGBA", (boyut, boyut), (0, 0, 0, 0))
    from PIL import ImageDraw
    ImageDraw.Draw(zemin).rounded_rectangle((0, 0, boyut - 1, boyut - 1), radius=56, fill=(31, 58, 95, 255))
    logo = renkli(kare, (255, 255, 255)).resize((int(boyut * 0.82),) * 2, Image.LANCZOS)
    zemin.alpha_composite(logo, ((boyut - logo.width) // 2, (boyut - logo.height) // 2))
    zemin.resize((64, 64), Image.LANCZOS).save(HEDEF / "favicon.png", optimize=True)
    zemin.save(HEDEF / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("Üretildi:", kare.size)


if __name__ == "__main__":
    main()
