"""Ders Programı modülünün (timetable + sinav) yeri.

Modül KAMYOSİS'e kopyalanmaz; ortak depodaki (ibrahimkvk94/blog, dal claude/elegant-fermi-mtxjbt) `dersprogrami/`
klasöründen kullanılır. Sırasıyla aranır:
1. KAMYOSIS_DERSPROGRAMI ortam değişkeni,
2. KAMYOSİS klasöründeki `.dersprogrami_yolu` dosyası (tek satır, yerel kurulum içindir; git'e girmez),
3. ortak depodaki komşu klasör: `<KAMYOSİS'in üst klasörü>/dersprogrami`.
"""

import os
from pathlib import Path


def bul(base_dir):
    base_dir = Path(base_dir)
    adaylar = []
    if os.environ.get("KAMYOSIS_DERSPROGRAMI"):
        adaylar.append(Path(os.environ["KAMYOSIS_DERSPROGRAMI"]))
    dosya = base_dir / ".dersprogrami_yolu"
    if dosya.exists():
        adaylar.append(Path(dosya.read_text(encoding="utf-8").strip()))
    adaylar.append(base_dir.parent / "dersprogrami")
    for yol in adaylar:
        if (yol / "timetable" / "__init__.py").exists() and (yol / "sinav" / "__init__.py").exists():
            return yol.resolve()
    raise RuntimeError(
        "Ders Programı modülü (dersprogrami/timetable ve sinav) bulunamadı. Denenen: "
        + ", ".join(str(y) for y in adaylar)
        + ". KAMYOSİS'i ortak depodaki kamyosis/ klasöründen çalıştırın ya da yolu KAMYOSIS_DERSPROGRAMI ortam "
          "değişkeniyle veya .dersprogrami_yolu dosyasıyla verin."
    )
