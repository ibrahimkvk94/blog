"""PPYS (Access) verilerini KAMYOSİS veritabanına aktarır.

Kullanım:
    python manage.py access_aktar                      # Masaüstündeki SinavMazeret_OrtakVeri.accdb
    python manage.py access_aktar "D:\\yedek\\OrtakVeri.accdb"
    python manage.py access_aktar --deneme             # aktarır, sonuçları gösterir, hiçbir şeyi kaydetmez

Kaynak dosya önce geçici bir klasöre kopyalanır ve kopya salt okunur açılır;
asıl Access dosyasına hiçbir şekilde yazılmaz ve kilit dosyası oluşmaz.
Komut tekrar çalıştırılabilir: kayıtlar Access ID'sine göre güncellenir.
"""

import secrets
import shutil
import string
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Birim, Yetki
from personel.models import Bolum, Personel, Secenek

VARSAYILAN_KAYNAK = Path.home() / "Desktop" / "SinavMazeret_OrtakVeri.accdb"

# PPYS modül kodu -> KAMYOSİS birimi
MODUL_BIRIM = {
    "PKS": "personel-bilgileri",
    "DMS": "ders-planlari",
    "DPS": "ders-planlari",
    "DDS": "ders-planlari",
    "BDD": "ders-planlari",
    "SMS": "sinav-planlari",
    "SPS": "sinav-planlari",
    "STS": "sinav-planlari",
}

# PPYS'deki bölüm kullanıcılarının (yönetici olmayan) varsayılan yetkileri
BOLUM_KULLANICISI_YETKILERI = [
    ("personel-bilgileri", Yetki.GORUNTULEME),
    ("plan-program", Yetki.DUZENLEME),
]


class _DenemeGeriAl(Exception):
    pass


def _gecici_parola(uzunluk=10):
    harfler = "".join(c for c in string.ascii_letters + string.digits if c not in "0OoIl1")
    return "".join(secrets.choice(harfler) for _ in range(uzunluk))


def _metin(deger):
    return (deger or "").strip()


class Command(BaseCommand):
    help = "PPYS (Access) verilerini aktarır. Asıl dosyaya dokunmaz; geçici kopyadan okur."

    def add_arguments(self, parser):
        parser.add_argument("kaynak", nargs="?", default=str(VARSAYILAN_KAYNAK),
                            help="SinavMazeret_OrtakVeri.accdb yolu (varsayılan: Masaüstü)")
        parser.add_argument("--deneme", action="store_true", help="Hiçbir şeyi kaydetmeden dene")
        parser.add_argument("--parola-dosyasi", default=str(settings.BASE_DIR / "ilk_parolalar.txt"),
                            help="Yeni kullanıcıların geçici parolalarının yazılacağı dosya")

    def handle(self, *args, **opts):
        try:
            import pyodbc
        except ImportError as e:
            raise CommandError("pyodbc kurulu değil: pip install pyodbc") from e

        kaynak = Path(opts["kaynak"])
        if not kaynak.exists():
            raise CommandError(f"Kaynak bulunamadı: {kaynak}")

        with tempfile.TemporaryDirectory(prefix="kamyosis_aktarim_") as gecici:
            kopya = Path(gecici) / kaynak.name
            shutil.copy2(kaynak, kopya)
            self.stdout.write(f"Kaynak: {kaynak} ({datetime.fromtimestamp(kaynak.stat().st_mtime):%d.%m.%Y %H:%M})")

            baglanti = pyodbc.connect(
                "DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};"
                f"DBQ={kopya};ReadOnly=1;Exclusive=1;",
                readonly=True,
            )
            try:
                self.cur = baglanti.cursor()
                self.yeni_parolalar = []
                try:
                    with transaction.atomic():
                        self._bolumler()
                        self._secenekler()
                        self._personel()
                        self._kullanicilar()
                        if opts["deneme"]:
                            raise _DenemeGeriAl
                except _DenemeGeriAl:
                    self.stdout.write(self.style.WARNING("Deneme modu: hiçbir değişiklik kaydedilmedi."))
                    return
            finally:
                baglanti.close()

        if self.yeni_parolalar:
            dosya = Path(opts["parola_dosyasi"])
            with dosya.open("a", encoding="utf-8") as f:
                f.write(f"# Aktarım {datetime.now():%d.%m.%Y %H:%M} - geçici parolalar (ilk girişte değiştirilecek)\n")
                for kullanici, parola in self.yeni_parolalar:
                    f.write(f"{kullanici}\t{parola}\n")
                f.write("\n")
            self.stdout.write(self.style.WARNING(
                f"{len(self.yeni_parolalar)} yeni kullanıcının geçici parolası yazıldı: {dosya}\n"
                "Parolaları kullanıcılara ilettikten sonra bu dosyayı silin."
            ))
        self.stdout.write(self.style.SUCCESS("Aktarım tamamlandı."))

    def _satirlar(self, sql):
        self.cur.execute(sql)
        kolonlar = [d[0] for d in self.cur.description]
        return [dict(zip(kolonlar, r)) for r in self.cur.fetchall()]

    def _rapor(self, ad, yeni, guncel):
        self.stdout.write(f"  {ad:<12} {yeni:>4} yeni, {guncel:>4} güncellendi")

    def _bolumler(self):
        yeni = guncel = 0
        for r in self._satirlar("SELECT BolumID, BolumAdi, MekanKodu FROM smBolum"):
            _, olustu = Bolum.objects.update_or_create(
                eski_id=r["BolumID"],
                defaults={"ad": _metin(r["BolumAdi"]), "kod": _metin(r["MekanKodu"]) or None},
            )
            yeni, guncel = yeni + olustu, guncel + (not olustu)
        self._rapor("Bölüm", yeni, guncel)

    def _secenekler(self):
        yeni = guncel = 0
        satirlar = self._satirlar("SELECT SecenekID, Tur, Metin, Aktif, Onde FROM smV47Secenek ORDER BY SecenekID")
        for sira, r in enumerate(satirlar, start=1):
            _, olustu = Secenek.objects.update_or_create(
                eski_id=r["SecenekID"],
                defaults={
                    "tur": _metin(r["Tur"]).upper(), "metin": _metin(r["Metin"]),
                    "aktif": bool(r["Aktif"]), "one_cikan": bool(r["Onde"]), "sira": sira,
                },
            )
            yeni, guncel = yeni + olustu, guncel + (not olustu)
        self._rapor("Seçenek", yeni, guncel)

    def _personel(self):
        bolumler = {b.eski_id: b for b in Bolum.objects.exclude(eski_id=None)}
        secenekler = {s.eski_id: s for s in Secenek.objects.exclude(eski_id=None)}
        yeni = guncel = 0
        for r in self._satirlar(
            "SELECT PersonelID, AdSoyad, BolumID, PersonelKodu, SinifID, RutbeID, UnvanID, Sicili FROM smPersonel"
        ):
            bolum = bolumler.get(r["BolumID"])
            if bolum is None:
                raise CommandError(f"Personel {r['PersonelID']}: bölüm {r['BolumID']} bulunamadı.")
            _, olustu = Personel.objects.update_or_create(
                eski_id=r["PersonelID"],
                defaults={
                    "ad_soyad": _metin(r["AdSoyad"]),
                    "personel_kodu": _metin(r["PersonelKodu"]),
                    "sicil": _metin(r["Sicili"]),
                    "bolum": bolum,
                    "rutbe": secenekler.get(r["RutbeID"]),
                    "sinif": secenekler.get(r["SinifID"]),
                    "unvan": secenekler.get(r["UnvanID"]),
                },
            )
            yeni, guncel = yeni + olustu, guncel + (not olustu)
        self._rapor("Personel", yeni, guncel)

    def _kullanicilar(self):
        User = get_user_model()
        bolumler = {b.eski_id: b for b in Bolum.objects.exclude(eski_id=None)}
        birimler = {b.slug: b for b in Birim.objects.all()}
        moduller = {}
        for r in self._satirlar("SELECT Kullanici, Kod, Acik FROM ppYoneticiModul"):
            if r["Acik"]:
                moduller.setdefault(_metin(r["Kullanici"]).lower(), set()).add(_metin(r["Kod"]).upper())

        yeni = guncel = yetki_sayisi = 0
        for r in self._satirlar(
            "SELECT Kullanici, BolumID, Yonetici, AnaYonetici, HesapAktif FROM smKullanici"
        ):
            ad = _metin(r["Kullanici"])
            ana_yonetici = bool(_metin(r["AnaYonetici"]))
            user, olustu = User.objects.get_or_create(username=ad)
            user.bolum = bolumler.get(r["BolumID"])
            user.is_active = bool(r["HesapAktif"])
            user.is_superuser = user.is_staff = ana_yonetici
            if olustu:
                parola = _gecici_parola()
                user.set_password(parola)
                user.parola_degismeli = True
                self.yeni_parolalar.append((ad, parola))
            user.save()
            yeni, guncel = yeni + olustu, guncel + (not olustu)

            if ana_yonetici:
                continue
            # Elle verilmiş yetkileri ezmemek için sadece eksik olanlar eklenir
            if r["Yonetici"]:
                istenen = {(MODUL_BIRIM[k], Yetki.YONETIM, Yetki.TUM)
                           for k in moduller.get(ad.lower(), ()) if k in MODUL_BIRIM}
            else:
                istenen = {(slug, seviye, Yetki.BOLUM) for slug, seviye in BOLUM_KULLANICISI_YETKILERI}
            for slug, seviye, kapsam in istenen:
                if slug in birimler:
                    _, eklendi = Yetki.objects.get_or_create(
                        kullanici=user, birim=birimler[slug], defaults={"seviye": seviye, "kapsam": kapsam},
                    )
                    yetki_sayisi += eklendi
        self._rapor("Kullanıcı", yeni, guncel)
        self.stdout.write(f"  {'Yetki':<12} {yetki_sayisi:>4} yeni")
