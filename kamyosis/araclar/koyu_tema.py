"""static/css/kamyosis.css'ten koyu tema katmanını (static/css/kamyosis-koyu.css) üretir.

Her kuraldaki açık zemin (background), koyu yazı (color) ve açık kenarlık (border) renkleri HSL'de ters çevrilerek
`[data-bs-theme="dark"] <seçici>` kuralına yazılır; durum renkleri (doygun orta tonlar) olduğu gibi kalır. Zaten koyu
tasarlanmış bölümler (sol menü, kişi kartı başlığı, teşkilat şeması başı …) ve kâğıt görünümlü resmî form dokunulmaz.
Elle yazılan koyu tema kuralları dosyanın başında (EL_YAZMASI) durur. CSS değişince yeniden çalıştırın:

    python araclar/koyu_tema.py
"""

import colorsys
import re
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
KAYNAK = KOK / "static/css/kamyosis.css"
HEDEF = KOK / "static/css/kamyosis-koyu.css"

# Bu seçicileri içeren kurallar atlanır (zaten koyu ya da kâğıt/baskı görünümü)
ATLA = ("pn-ipucu", "menu-ara", "menu-yildiz", "menu-ipucu", "kenar", "marka", "giris", "org-kok", "avatar", "yk-profil", "yk-kagit", "yk-resmi", "yk-sayim", "yk-beyan",
        "yk-isaretler", "tk-mudurluk", "tk-yardimci", "tk-kol-bas", "tk-sayi", "tk-hat", "yk-foto-bos", "nd-btn.aktif",
        "islem-cubugu .nd-", "btn-check:checked", "yk-hucre", "text-bg-primary", "btn-primary", "btn-outline-primary",
        "nav-pills", "form-check-input:checked", ":root", "@page")

EL_YAZMASI = '''/* KAMYOSİS koyu tema. Bu dosya araclar/koyu_tema.py ile üretilir; elle değişiklik yalnız bu başlık bölümüne. */
[data-bs-theme="dark"] {
  --km-zemin: #0d141d;
  --km-kenarlik: #263445;
  --km-yuzey: #141d29;
  --km-yuzey-2: #1a2533;
  --bs-body-bg: #0d141d;
  --bs-body-color: #d5dde7;
  --bs-secondary-color: #94a3b8;
  --bs-tertiary-bg: #1a2533;
  --bs-border-color: #263445;
  --bs-link-color: #8fb4dc;
  --bs-link-color-rgb: 143, 180, 220;
  --bs-link-hover-color: #b5cfea;
  --bs-primary: #5b8cc0;
  --bs-primary-rgb: 91, 140, 192;
  color-scheme: dark;
}
[data-bs-theme="dark"] body { background: var(--km-zemin); color: var(--bs-body-color); }
[data-bs-theme="dark"] .btn-light, [data-bs-theme="dark"] .geri-btn {
  --bs-btn-bg: #1a2533; --bs-btn-border-color: #2c3b4f; --bs-btn-color: #d5dde7;
  --bs-btn-hover-bg: #223044; --bs-btn-hover-border-color: #3a4c63; --bs-btn-hover-color: #fff;
  --bs-btn-active-bg: #2a3a50; --bs-btn-active-border-color: #3a4c63; --bs-btn-active-color: #fff; }
[data-bs-theme="dark"] .btn-outline-primary { --bs-btn-color: #8fb4dc; --bs-btn-border-color: #4a77a6; --bs-btn-hover-color: #fff; }
[data-bs-theme="dark"] .btn-outline-secondary { --bs-btn-color: #b8c4d2; --bs-btn-border-color: #3a4c63; }
[data-bs-theme="dark"] .bg-white, [data-bs-theme="dark"] .bg-light { background-color: var(--km-yuzey) !important; }
[data-bs-theme="dark"] .text-dark { color: #e2e8f0 !important; }
[data-bs-theme="dark"] .text-bg-light { background-color: #223044 !important; color: #d5dde7 !important; }
[data-bs-theme="dark"] .table-light { --bs-table-bg: #1a2533; --bs-table-color: #d5dde7; --bs-table-border-color: #263445; }
[data-bs-theme="dark"] .table { --bs-table-color: #d5dde7; --bs-table-border-color: #263445; }
[data-bs-theme="dark"] .table-active, [data-bs-theme="dark"] .table-hover > tbody > tr:hover > * { --bs-table-bg-state: rgba(143, 180, 220, .08); }
[data-bs-theme="dark"] .alert-warning { --bs-alert-bg: #2b2210; --bs-alert-color: #f5d68a; --bs-alert-border-color: #5a4515; }
[data-bs-theme="dark"] .alert-info { --bs-alert-bg: #0f2433; --bs-alert-color: #9fd3f0; --bs-alert-border-color: #1d4660; }
[data-bs-theme="dark"] .alert-success { --bs-alert-bg: #0f2a1b; --bs-alert-color: #9ee6b8; --bs-alert-border-color: #1d5233; }
[data-bs-theme="dark"] .alert-danger { --bs-alert-bg: #2f1214; --bs-alert-color: #f6a7a7; --bs-alert-border-color: #5c2226; }
[data-bs-theme="dark"] .alert-secondary { --bs-alert-bg: #1a2533; --bs-alert-color: #c3cdd9; --bs-alert-border-color: #2c3b4f; }
[data-bs-theme="dark"] .yk-cip { background: color-mix(in srgb, var(--renk) 22%, #0d141d); border-color: color-mix(in srgb, var(--renk) 50%, #0d141d);
  color: color-mix(in srgb, var(--renk) 55%, #fff); }
[data-bs-theme="dark"] .yk-profil .yk-cip { background: rgba(255, 255, 255, .95); color: var(--renk); }
[data-bs-theme="dark"] .yk-hucre.kismi { background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--renk) 35%, #0d141d) 0 5px, #0d141d 5px 10px); }
[data-bs-theme="dark"] .yk-kagit { box-shadow: 0 0 0 1px #263445, 0 8px 28px rgba(0, 0, 0, .5); }
[data-bs-theme="dark"] .ts-control, [data-bs-theme="dark"] .ts-dropdown { background: #141d29; color: #d5dde7; border-color: #2c3b4f; }
[data-bs-theme="dark"] .ts-control input { color: #d5dde7; }
[data-bs-theme="dark"] .ts-dropdown .active { background: #223044; color: #fff; }
[data-bs-theme="dark"] .dp-cerceve { background: #0d141d; }
[data-bs-theme="dark"] .tk-mudurluk { box-shadow: 0 0 0 1px #c9a227, 0 6px 18px rgba(0, 0, 0, .4); }
[data-bs-theme="dark"] .bolum-baslik .bi, [data-bs-theme="dark"] .birim-ikon, [data-bs-theme="dark"] .org-dal-baslik .bi { color: #8fb4dc; }
/* sol menü: koyu temada lacivert yerine zeminle uyumlu koyu gri-lacivert, altın vurgu kalır */
[data-bs-theme="dark"] .kenar, [data-bs-theme="dark"] .kenar.offcanvas-lg,
[data-bs-theme="dark"] .kenar.offcanvas-lg .kenar-ust { background-color: #0a1119 !important; }
[data-bs-theme="dark"] .kenar { border-right: 1px solid #1b2634; color: #c9d4e2; }
[data-bs-theme="dark"] .kenar-ust { border-bottom-color: #1b2634; }
[data-bs-theme="dark"] .kenar .nav-link { color: #c9d4e2; }
[data-bs-theme="dark"] .kenar .nav-link:hover { background: rgba(143, 180, 220, .08); color: #fff; }
[data-bs-theme="dark"] .kenar .nav-link.active { background: #172231; color: #fff; }
[data-bs-theme="dark"] .kenar-menu ul ul { border-left-color: #1b2634; }
[data-bs-theme="dark"] .menu-baslik, [data-bs-theme="dark"] .menu-ipucu { color: #7d8ea3; }
[data-bs-theme="dark"] .menu-ara input { background: #111a25; border-color: #1f2c3c; }
[data-bs-theme="dark"] .menu-ara input:focus { background: #142030; }
html[data-bs-theme="dark"].kenar-dar .kenar.gezinti { box-shadow: 8px 0 28px rgba(0, 0, 0, .6); }
[data-bs-theme="dark"] .nav-pills .nav-link:not(.active) { color: #b5cfea; }
[data-bs-theme="dark"] .nav-pills .nav-link:not(.active):hover { color: #fff; background: rgba(143, 180, 220, .08); }

/* ---- aşağısı otomatik üretilir ---- */
[data-bs-theme="dark"] .pn { --pn-mevcut: #3a4a5f; --pn-iz: #1c2838; --pn-izgara: #223044; --pn-yazi: #e2e8f0; --pn-soluk: #94a3b8;
  --pn-zemin: #111922; --pn-k1: #1d3550; --pn-k2: #254c78; --pn-k3: #3068a3; --pn-k4: #5a90c9; --pn-k5: #9cc2ea; --pn-k-yazi: #0d141d;
  --pn-subay: #8fb8e6; --pn-astsubay: #2f8f9f; --pn-sivil: #e0bd4a; --pn-lacivert: #6f9fd3; --pn-camgobegi: #2aa3bd; }
[data-bs-theme="dark"] .pn-ipucu { background: #e2e8f0; color: #0f172a; }
'''

HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _hex(r, g, b):
    return "#" + "".join(f"{round(max(0, min(1, x)) * 255):02x}" for x in (r, g, b))


def _hls(h):
    return colorsys.rgb_to_hls(*_rgb(h))


def zemin(h):
    """Açık zemin → koyu yüzey (renk tonu korunur)."""
    hh, l, s = _hls(h)
    if l < .8:
        return None
    if s < .2:  # beyaz ve gri zeminler: KAMYOSİS lacivertine çalan koyu yüzey
        hh, s = .59, .32
    return _hex(*colorsys.hls_to_rgb(hh, .1 + (1 - l) * .55, s * .45 if s > .32 else s))


def yazi(h):
    """Koyu yazı → açık yazı; gri orta tonlar biraz açılır."""
    hh, l, s = _hls(h)
    if l <= .42:
        return _hex(*colorsys.hls_to_rgb(hh, .93 - l * .45, min(s, .55)))
    if l < .62 and s < .3:
        return _hex(*colorsys.hls_to_rgb(hh, .68, s))
    return None


def kenar(h):
    hh, l, s = _hls(h)
    if l < .7:
        return None
    if s < .2:
        hh, s = .59, .3
    return _hex(*colorsys.hls_to_rgb(hh, .2 + (1 - l) * .35, s * .4 if s > .3 else s))


def _degistir(deger, f):
    degisti = False

    def r(m):
        nonlocal degisti
        y = f("#" + m.group(1))
        if y is None:
            return m.group(0)
        degisti = True
        return y

    sonuc = HEX.sub(r, deger)
    if "rgba(255,255,255" in deger.replace(" ", "") and f is zemin:
        sonuc = re.sub(r"rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*([0-9.]+)\s*\)", r"rgba(13, 20, 29, \1)", sonuc)
        degisti = True
    return sonuc if degisti else None


def donustur(bildirim):
    ad, _, deger = bildirim.partition(":")
    ad, deger = ad.strip(), deger.strip()
    if not deger or "var(" in deger and not HEX.search(deger):
        return None
    if ad in ("background", "background-color"):
        if "gradient" in deger and "repeating" not in deger:
            y = _degistir(deger, zemin)
        else:
            y = _degistir(deger, zemin)
    elif ad == "color":
        y = _degistir(deger, yazi)
    elif ad.startswith("border") or ad == "outline":
        y = _degistir(deger, kenar)
    elif ad == "box-shadow" and "inset" not in deger:
        y = None
    else:
        y = None
    return f"{ad}: {y}" if y else None


def kurallar(css):
    """(seçici, gövde) çiftleri; @media içindeki kurallar @media ile birlikte döner (print atlanır)."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    i, n, out, medya = 0, len(css), [], []
    while i < n:
        j = css.find("{", i)
        if j < 0:
            break
        secici = css[i:j].strip()
        if secici.startswith("@media") or secici.startswith("@supports"):
            medya.append(secici)
            i = j + 1
            continue
        if secici.startswith("@"):
            # @keyframes, @view-transition: blokları atla
            derinlik, k = 1, j + 1
            while derinlik and k < n:
                derinlik += {"{": 1, "}": -1}.get(css[k], 0)
                k += 1
            i = k
        else:
            k = css.find("}", j)
            out.append((tuple(medya), secici, css[j + 1:k]))
            i = k + 1
        # kapanan @media blokları
        while medya:
            m = re.match(r"\s*}", css[i:])
            if not m:
                break
            medya.pop()
            i += m.end()
    return out


def uret():
    satirlar = [EL_YAZMASI]
    for medya, secici, govde in kurallar(KAYNAK.read_text(encoding="utf-8")):
        if any("print" in m for m in medya) or any(a in secici for a in ATLA):
            continue
        yeni = [d for d in (donustur(b) for b in govde.split(";") if b.strip()) if d]
        if not yeni:
            continue
        seciciler = ", ".join(f'[data-bs-theme="dark"] {s.strip()}' for s in secici.split(","))
        kural = f"{seciciler} {{ {'; '.join(yeni)}; }}"
        for m in reversed(medya):
            kural = f"{m} {{ {kural} }}"
        satirlar.append(kural)
    HEDEF.write_text("\n".join(satirlar) + "\n", encoding="utf-8")
    return len(satirlar) - 1


if __name__ == "__main__":
    print(f"{uret()} koyu tema kuralı yazıldı: {HEDEF.relative_to(KOK)}")
