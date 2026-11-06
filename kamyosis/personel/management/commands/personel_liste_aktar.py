"""Personel listesinden rütbe/sınıf/unvan/bölüm/sicil aktarımı.

    python manage.py personel_liste_aktar aSc\\personel_listesi.xlsx            # sadece önizleme
    python manage.py personel_liste_aktar aSc\\personel_listesi.xlsx --uygula   # kaydet
    ... --yeni-ekle   listede olup personelde olmayanları da ekler

Önizleme ayrıca <dosya>_onizleme.csv olarak yazılır (Excel'de açılabilir).
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from personel.liste_aktarimi import oku, planla, uygula
from personel.models import Personel

ALAN_ADI = {"rutbe": "Rütbe", "sinif": "Sınıf", "unvan": "Unvan", "bolum": "Bölüm", "sicil": "Sicil"}


def _yaz(deger):
    if isinstance(deger, tuple):
        return f"{deger[1]} (yeni seçenek)"
    return "" if deger is None else str(deger)


class Command(BaseCommand):
    help = "Personel listesinden (Excel/CSV) rütbe, sınıf, unvan, bölüm ve sicil bilgilerini aktarır."

    def add_arguments(self, parser):
        parser.add_argument("dosya")
        parser.add_argument("--uygula", action="store_true", help="Değişiklikleri kaydet (yoksa sadece önizleme)")
        parser.add_argument("--yeni-ekle", action="store_true", help="Personelde olmayanları yeni kayıt olarak ekle")

    def handle(self, *args, **o):
        yol = Path(o["dosya"])
        if not yol.exists():
            raise CommandError(f"Dosya bulunamadı: {yol}")
        satirlar = oku(yol)
        plan = planla(satirlar)
        onizleme = yol.with_name(yol.stem + "_onizleme.csv")
        with onizleme.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Satır", "Listede ad", "Durum", "KAMYOSİS'teki kayıt", "Değişecek alanlar", "Notlar"])
            for d in sorted(plan, key=lambda d: ({"cozulemedi": 0, "yeni": 1, "benzer": 2, "eslesti": 3}[d.durum], int(d.satir.satir))):
                degisim = "; ".join(f"{ALAN_ADI[a]}: {_yaz(e) or '–'} → {_yaz(y)}" for a, (e, y) in d.alanlar.items())
                w.writerow([d.satir.satir, d.satir.ad, d.durum, d.personel.ad_soyad if d.personel else "", degisim, " | ".join(d.notlar)])

        say = {k: sum(1 for d in plan if d.durum == k) for k in ("eslesti", "benzer", "yeni", "cozulemedi")}
        degisen = sum(1 for d in plan if d.personel and d.alanlar)
        listede = {d.personel.pk for d in plan if d.personel}
        disarida = Personel.objects.filter(aktif=True).exclude(pk__in=listede).count()
        self.stdout.write(f"Listedeki satır: {len(satirlar)} · farklı kişi: {len(plan)}")
        self.stdout.write(f"  Ad birebir eşleşen: {say['eslesti']} · benzer adla eşleşen: {say['benzer']} · "
                          f"personelde olmayan: {say['yeni']} · çözülemeyen: {say['cozulemedi']}")
        self.stdout.write(f"  Bilgisi değişecek personel: {degisen}")
        alanlar = {}
        for d in plan:
            for a in d.alanlar:
                alanlar[a] = alanlar.get(a, 0) + 1
        self.stdout.write("  Alan bazında: " + ", ".join(f"{ALAN_ADI[a]} {n}" for a, n in alanlar.items()))
        self.stdout.write(f"  KAMYOSİS'te olup listede olmayan aktif personel: {disarida}")
        self.stdout.write(f"Önizleme: {onizleme}")
        if o["uygula"]:
            with transaction.atomic():
                g, e, yeni = uygula(plan, yeni_ekle=o["yeni_ekle"])
            self.stdout.write(self.style.SUCCESS(f"Kaydedildi: {g} güncellendi, {e} eklendi."
                                                 + (f" Yeni sınıf seçenekleri: {', '.join(yeni)}" if yeni else "")))
        else:
            self.stdout.write(self.style.WARNING("Önizleme: hiçbir şey kaydedilmedi (kaydetmek için --uygula)."))
