"""Ders takibi iş kuralları (PPYS DDS'ten uyarlanmıştır; bkz. docs/ppys_is_kurallari.md 1.1, 4.1).

- Tarihli dersler, o tarihte geçerli program sürümünden üretilir; tatil günleri atlanır.
- Tarihi geçen ders kendiliğinden "yapıldı" sayılır (beyan/teyit yok; 03.11.2026 kararı).
- Bir dersin öğretmeni sadece kesinleşmiş devirle değişir; devir geçmiş derse de açılabilir.
- Devir: talep → onay → kesin; iade (talep/onay'dan), iptal (kesin'den); kararlar talep grubunun tamamına uygulanır.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404
from django.utils import timezone

from core.models import Yetki
from core.yetki import DUZENLEME, GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from program.models import ProgramHucresi, ProgramSurumu

from .models import DersKaydi, DevirTalebi, Gunluk, Tatil

BIRIM_DERS = "ders-planlari"
BIRIM_PLAN = "plan-program"


class TakipHatasi(Exception):
    pass


# ---------------------------------------------------------------- yetkiler

@dataclass
class TakipYetkisi:
    goruntule: bool = False
    bolum_adina: bool = False      # bölüm adına devir talebi
    kapsam_bolum: object = None     # None = tüm bölümler; aksi halde Bolum
    onay: bool = False              # devir onayı ve iadesi
    kesin: bool = False             # devir kesinleştirme ve iptali
    personel: object = None         # kullanıcının kendi personel kaydı ("Derslerim")

    def bolumu_kapsar(self, bolum):
        return self.kapsam_bolum is None or (bolum is not None and bolum.pk == self.kapsam_bolum.pk)


def yetki(request):
    if hasattr(request, "_takip_yetkisi"):
        return request._takip_yetkisi
    y = TakipYetkisi(personel=getattr(request.user, "personel", None))
    try:
        ds, dk = etkin_yetki(request, birim_bul(request, BIRIM_DERS))
        ps, _ = etkin_yetki(request, birim_bul(request, BIRIM_PLAN))
    except Http404:
        ds = ps = 0
        dk = None
    y.goruntule = ds >= GORUNTULEME
    y.bolum_adina = ds >= DUZENLEME
    y.onay = ds >= YONETIM
    y.kesin = ps >= YONETIM
    if dk == Yetki.BOLUM:
        y.kapsam_bolum = request.user.bolum
        if y.kapsam_bolum is None:  # bölümü atanmamış bölüm kullanıcısı hiçbir şeyi kapsamaz
            y.goruntule = y.bolum_adina = y.onay = False
    request._takip_yetkisi = y
    return y


# ---------------------------------------------------------------- tarihli dersler

@dataclass
class Satir:
    tarih: date
    hucre: ProgramHucresi
    ogretmen: object                # ProgramOgretmeni (programdaki asıl öğretmen)
    kayit: DersKaydi = None
    devir: DevirTalebi = None       # etkin devir (talep/onay/kesin)

    @property
    def anahtar(self):
        return f"{self.tarih:%Y%m%d}-{self.hucre.pk}-{self.ogretmen.pk}"

    @property
    def asil_personel(self):
        return self.ogretmen.personel

    @property
    def etkin_personel(self):
        if self.devir and self.devir.durum == DevirTalebi.KESIN:
            return self.devir.yeni_personel
        return self.ogretmen.personel

    @property
    def etkin_ad(self):
        p = self.etkin_personel
        return p.ad_soyad if p else self.ogretmen.ad

    @property
    def bolum(self):
        p = self.etkin_personel
        if p is not None:
            return p.bolum
        return self.ogretmen.tahmini_bolum

    @property
    def asil_bolum(self):
        p = self.asil_personel
        return p.bolum if p is not None else self.ogretmen.tahmini_bolum

    @property
    def devir_bekliyor(self):
        return bool(self.devir and self.devir.durum in DevirTalebi.BEKLEYEN)

    @property
    def yapildi(self):
        return self.tarih < timezone.localdate()

    @property
    def durum(self):
        if self.devir_bekliyor:
            return "devir"
        return "yapildi" if self.yapildi else "gelecek"


def anahtar_coz(anahtar):
    try:
        t, h, o = anahtar.split("-")
        return date(int(t[:4]), int(t[4:6]), int(t[6:8])), int(h), int(o)
    except (ValueError, AttributeError):
        raise TakipHatasi("Geçersiz ders seçimi.")


def _gecerli_surumler(bas, bit):
    """Her tarih için geçerli sürüm: yayındaki, tarihi kapsayan, en son yayınlanan."""
    yayinda = list(
        ProgramSurumu.objects.filter(durum=ProgramSurumu.YAYINDA, baslangic__lte=bit)
        .exclude(bitis__lt=bas).order_by("-yayin_zamani", "-pk")
    )
    sonuc = {}
    g = bas
    while g <= bit:
        sonuc[g] = next((s for s in yayinda if s.baslangic <= g and (s.bitis is None or s.bitis >= g)), None)
        g += timedelta(days=1)
    return sonuc


def beklenen_dersler(bas, bit, *, kisim=None, personel=None, bolum=None, ogretmen=None):
    """[bas, bit] aralığındaki tarihli dersler (öğretmen başına bir satır)."""
    surumler = _gecerli_surumler(bas, bit)
    tatiller = set(Tatil.objects.filter(tarih__range=(bas, bit)).values_list("tarih", flat=True))
    hucre_onbellek = {}

    def surum_hucreleri(surum):
        if surum.pk not in hucre_onbellek:
            qs = (ProgramHucresi.objects.filter(surum=surum)
                  .select_related("haftalik_ders__ders__bolum", "derslik")
                  .prefetch_related("haftalik_ders__ogretmenler__personel__bolum",
                                    "haftalik_ders__ogretmenler__tahmini_bolum",
                                    "haftalik_ders__kisimlar", "haftalik_ders__gruplar"))
            if kisim is not None:
                qs = qs.filter(haftalik_ders__kisimlar=kisim)
            gunler = {}
            for h in qs:
                gunler.setdefault(h.gun, []).append(h)
            hucre_onbellek[surum.pk] = gunler
        return hucre_onbellek[surum.pk]

    satirlar = []
    for tarih, surum in surumler.items():
        if surum is None or tarih in tatiller:
            continue
        for h in surum_hucreleri(surum).get(tarih.isoweekday(), []):
            for o in h.haftalik_ders.ogretmenler.all():
                satirlar.append(Satir(tarih=tarih, hucre=h, ogretmen=o))

    kayitlar = {
        (k.tarih, k.hucre_id, k.ogretmen_id): k
        for k in DersKaydi.objects.filter(tarih__range=(bas, bit)).prefetch_related(
            Prefetch("devirler", queryset=DevirTalebi.objects.filter(durum__in=DevirTalebi.ETKIN).select_related("yeni_personel__bolum"), to_attr="etkin_devirler")
        )
    }
    for s in satirlar:
        s.kayit = kayitlar.get((s.tarih, s.hucre.pk, s.ogretmen.pk))
        if s.kayit and s.kayit.etkin_devirler:
            s.devir = s.kayit.etkin_devirler[0]

    if ogretmen is not None:
        satirlar = [s for s in satirlar if s.ogretmen.pk == ogretmen.pk]
    if personel is not None:
        satirlar = [s for s in satirlar if personel in (s.etkin_personel, s.asil_personel)]
    if bolum is not None:
        satirlar = [s for s in satirlar if bolum in (s.bolum, s.asil_bolum)]
    satirlar.sort(key=lambda s: (s.tarih, s.hucre.saat, s.etkin_ad))
    return satirlar


def satirlari_getir(anahtarlar):
    """Seçilen anahtarların satırları (geçerli programda olmayanlar hata verir)."""
    cozulen = [anahtar_coz(a) for a in anahtarlar]
    if not cozulen:
        raise TakipHatasi("Hiç ders seçilmedi.")
    tarihler = [c[0] for c in cozulen]
    tum = {s.anahtar: s for s in beklenen_dersler(min(tarihler), max(tarihler))}
    sonuc = []
    for a in anahtarlar:
        if a not in tum:
            raise TakipHatasi("Seçilen derslerden biri artık geçerli programda değil. Sayfayı yenileyin.")
        sonuc.append(tum[a])
    return sonuc


def _kayit(s):
    if s.kayit is None:
        s.kayit, _ = DersKaydi.objects.get_or_create(tarih=s.tarih, hucre=s.hucre, ogretmen=s.ogretmen)
        s.kayit.etkin_devirler = []
    return s.kayit


def _gunluk(user, islem, satirlar, ek=""):
    ayrinti = "\n".join(f"{s.tarih:%d.%m.%Y} {s.hucre.saat}. saat {s.hucre.haftalik_ders.ders.kod} {s.etkin_ad}" for s in satirlar)
    Gunluk.objects.create(kullanici=user, islem=islem, ayrinti=(ek + "\n" + ayrinti).strip())


# ---------------------------------------------------------------- devir

def talep_yetkisi_var(y, s):
    return y.bolum_adina and y.bolumu_kapsar(s.asil_bolum)


def cakismalar(satirlar, yeni_personel, haric_blok=None):
    """Yeni personelin aynı tarih ve saatte başka dersi ya da bekleyen devri var mı?"""
    if not satirlar:
        return []
    tarihler = [s.tarih for s in satirlar]
    dolu = {(d.tarih, d.hucre.saat) for d in beklenen_dersler(min(tarihler), max(tarihler), personel=yeni_personel)
            if d.etkin_personel == yeni_personel}
    bekleyen = DevirTalebi.objects.filter(yeni_personel=yeni_personel, durum__in=DevirTalebi.ETKIN, kayit__tarih__range=(min(tarihler), max(tarihler)))
    if haric_blok:
        bekleyen = bekleyen.exclude(blok=haric_blok)
    dolu |= {(d.kayit.tarih, d.kayit.hucre.saat) for d in bekleyen.select_related("kayit__hucre")}
    return [s for s in satirlar if (s.tarih, s.hucre.saat) in dolu]


@transaction.atomic
def devir_talep_et(user, y, satirlar, yeni_personel, gerekce):
    if not (gerekce or "").strip():
        raise TakipHatasi("Gerekçe zorunludur.")
    hatalar = []
    for s in satirlar:
        if not talep_yetkisi_var(y, s):
            hatalar.append(f"{s.tarih:%d.%m} {s.hucre.saat}. saat: bu dersin bölümü için talep yetkiniz yok")
        elif s.devir:
            hatalar.append(f"{s.tarih:%d.%m} {s.hucre.saat}. saat: zaten etkin bir devir talebi var")
        elif s.etkin_personel == yeni_personel:
            hatalar.append(f"{s.tarih:%d.%m} {s.hucre.saat}. saat: ders zaten bu personelde")
    for s in cakismalar(satirlar, yeni_personel):
        hatalar.append(f"{s.tarih:%d.%m} {s.hucre.saat}. saat: {yeni_personel.ad_soyad} o saatte dolu")
    if hatalar:
        raise TakipHatasi("Talep oluşturulamadı:\n" + "\n".join(hatalar))
    blok = None
    for s in satirlar:
        d = DevirTalebi.objects.create(kayit=_kayit(s), yeni_personel=yeni_personel, gerekce=gerekce.strip(),
                                       isteyen=user, **({"blok": blok} if blok else {}))
        blok = d.blok
    _gunluk(user, "Devir talebi", satirlar, f"→ {yeni_personel.ad_soyad}: {gerekce.strip()}")
    return blok


GECISLER = {
    # işlem: (izin verilen önceki durumlar, yeni durum, gereken yetki)
    "onayla": ((DevirTalebi.TALEP,), DevirTalebi.ONAY, "onay"),
    "iade": ((DevirTalebi.TALEP, DevirTalebi.ONAY), DevirTalebi.IADE, "onay"),
    "kesinlestir": ((DevirTalebi.ONAY,), DevirTalebi.KESIN, "kesin"),
    "iptal": ((DevirTalebi.KESIN,), DevirTalebi.IPTAL, "kesin"),
}


@transaction.atomic
def devir_karar(user, y, blok, islem, not_):
    if islem not in GECISLER:
        raise TakipHatasi("Geçersiz işlem.")
    onceki, yeni, gereken = GECISLER[islem]
    if not getattr(y, gereken):
        raise TakipHatasi("Bu işlem için yetkiniz yok.")
    if not (not_ or "").strip():
        raise TakipHatasi("Karar gerekçesi zorunludur.")
    talepler = list(DevirTalebi.objects.select_for_update().filter(blok=blok).select_related("kayit__hucre", "yeni_personel"))
    if not talepler:
        raise TakipHatasi("Talep bulunamadı.")
    if any(t.durum not in onceki for t in talepler):
        raise TakipHatasi("Talep bu sırada değişmiş; sayfayı yenileyip tekrar deneyin.")
    if yeni in (DevirTalebi.ONAY, DevirTalebi.KESIN):
        anahtarlar = [f"{t.kayit.tarih:%Y%m%d}-{t.kayit.hucre_id}-{t.kayit.ogretmen_id}" for t in talepler]
        satirlar = satirlari_getir(anahtarlar)
        if cakismalar(satirlar, talepler[0].yeni_personel, haric_blok=blok):
            raise TakipHatasi(f"{talepler[0].yeni_personel.ad_soyad} artık bu saatlerden en az birinde dolu.")
    simdi = timezone.now()
    for t in talepler:
        t.durum, t.karar_veren, t.karar_zamani, t.karar_notu = yeni, user, simdi, not_.strip()
        if yeni == DevirTalebi.ONAY:
            t.onaylayan, t.onay_zamani = user, simdi
        elif yeni == DevirTalebi.KESIN:
            t.kesinlestiren, t.kesin_zamani = user, simdi
        t.save()
    Gunluk.objects.create(kullanici=user, islem=f"Devir {dict(DevirTalebi.DURUM_SECENEKLERI)[yeni].lower()}",
                          ayrinti=f"{len(talepler)} ders → {talepler[0].yeni_personel.ad_soyad}: {not_.strip()}")
    return talepler


def yayin_engeli(baslangic):
    """Program yayınında, başlangıçtan itibaren devir görmüş ders varsa açıklama döner."""
    if DevirTalebi.objects.filter(kayit__tarih__gte=baslangic, durum__in=DevirTalebi.ETKIN).exists():
        return "Bu tarihten sonra etkin devir talepleri var."
    return None


# ---------------------------------------------------------------- ana sayfa

PANEL_GUN_SAYISI = 14


def panel_gorevleri(request, ek=()):
    """Ana sayfadaki "yapılacaklar": kullanıcının yetkisine göre bekleyen işler.

    renk: "eksik" = sizden bekleniyor, "bekliyor" = başkasının kararı bekleniyor, "tamam" = iş yok.
    """
    from django.urls import reverse
    from django.utils.http import urlencode

    from program.models import ProgramOgretmeni

    y = yetki(request)
    gorevler = list(ek)  # diğer modüllerin görevleri (ör. ders mazereti); "Bekleyen işiniz yok" bunları da sayar
    if not (y.goruntule or y.bolum_adina):
        return gorevler

    bit = timezone.localdate() - timedelta(days=1)  # dünkü dahil geçmiş günler: hepsi yapılmış sayılır
    bas = bit - timedelta(days=PANEL_GUN_SAYISI - 1)
    aralik = urlencode({"bas": bas.isoformat(), "bit": bit.isoformat()})
    satirlar = beklenen_dersler(bas, bit, bolum=y.kapsam_bolum)

    def blok_sayisi(qs):
        return qs.values("blok").distinct().count()

    if y.onay:
        n = blok_sayisi(DevirTalebi.objects.filter(durum=DevirTalebi.TALEP))
        if n:
            gorevler.append({"renk": "eksik", "ikon": "arrow-left-right", "sayi": n, "ad": "Onayınızı bekleyen devir",
                             "aciklama": "Ders devri talepleri", "url": reverse("takip:devirler")})
    if y.kesin:
        n = blok_sayisi(DevirTalebi.objects.filter(durum=DevirTalebi.ONAY))
        if n:
            gorevler.append({"renk": "eksik", "ikon": "arrow-left-right", "sayi": n, "ad": "Kesinleştirmenizi bekleyen devir",
                             "aciklama": "Onaylanmış, son kararı bekleyen talepler", "url": reverse("takip:devirler")})
    if y.bolum_adina and not y.onay:
        n = blok_sayisi(DevirTalebi.objects.filter(isteyen=request.user, durum__in=DevirTalebi.BEKLEYEN))
        if n:
            gorevler.append({"renk": "bekliyor", "ikon": "hourglass-split", "sayi": n, "ad": "Sonuç bekleyen devir talebiniz",
                             "aciklama": "Onay veya kesinleştirme bekleniyor", "url": reverse("takip:devirler")})

    if y.onay:
        if ProgramSurumu.objects.gecerli() is None:
            gorevler.append({"renk": "eksik", "ikon": "calendar-x", "sayi": None, "ad": "Yayında ders programı yok",
                             "aciklama": "Programı yayınlayın; ders takibi ancak o zaman başlar", "url": reverse("program:surumler")})
        n = ProgramOgretmeni.objects.filter(durum=ProgramOgretmeni.BEKLIYOR).count()
        if n:
            gorevler.append({"renk": "eksik", "ikon": "person-exclamation", "sayi": n, "ad": "Eşleştirme bekleyen öğretmen",
                             "aciklama": "aSc öğretmenlerini personelle eşleştirin", "url": reverse("program:ogretmenler")})

    tamam = len(satirlar)
    if tamam or not gorevler:
        gorevler.append({"renk": "tamam", "ikon": "check-circle", "sayi": tamam or None,
                         "ad": "Yapılan ders" if tamam else "Bekleyen işiniz yok",
                         "aciklama": f"Son {PANEL_GUN_SAYISI} gün" if tamam else "Her şey güncel",
                         "url": f"{reverse('takip:gunluk')}?{aralik}" if tamam else ""})
    return gorevler