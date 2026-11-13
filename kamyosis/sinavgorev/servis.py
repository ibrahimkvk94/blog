"""Sınav görev puantajı iş kuralları (PPYS STS).

- Yıl eğitim-öğretim yılıdır: 1 Ekim'de başlar (puantaj Ekim'de sıfırlanır).
- Görev puanı: hafta içi görev 1, hafta sonu (Cumartesi/Pazar) görevi 1,5. Her oturum ayrı görevdir.
- Skor = görev puanı + z; z = (haftalık ders saati − ortalama) / standart sapma (popülasyon). Ders saati bir Program
  Hazırlama programından okunur; ortalama, sınav görevi rolü olan ve programda eşleşen personelden hesaplanır,
  diğerlerinin z'si 0'dır. Ders yükü yüksek olanın skoru yüksek çıkar ve daha az görev alır.
- Gözetmen dağıtımı (Sınav Planlama) onceki_puanlar() ile her öğretmenin yıl içindeki skorunu (dağıtılan dönem
  hariç) alır ve yeni görevleri skoru düşükten başlayarak dengeler.
- Bölüm kapsamlı kullanıcı yalnızca kendi bölümünü görür; işleme, elle görev ve rol değişikliği yönetim yetkisidir.
- Salon amiri kuralı (Mehmet, 03.11.2026): unvanı Dr.Öğt.Üyesi (ve Doç.Dr., Prof.Dr.) ya da rütbesi Yzb. üstü (Bnb. ve
  yukarısı) olan personele "Kurala göre salon amiri ata" ile A rolü eklenir; kalan düzenleme elle yapılır.
"""

import datetime
import math
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction
from django.http import Http404

from core.models import Yetki
from core.yetki import GORUNTULEME, YONETIM, birim_bul, etkin_yetki
from dersprogrami_kopru.kunye import ogretmen_eslesmesi
from personel.models import Personel

from .models import SinavGorevi

BIRIM = "sinav-gorev-puantaji"
HAFTA_SONU_PUANI = 1.5


@dataclass
class PuantajYetkisi:
    goruntule: bool = False
    yonetim: bool = False
    kapsam_bolum: object = None


def yetki(request):
    if hasattr(request, "_puantaj_yetkisi"):
        return request._puantaj_yetkisi
    y = PuantajYetkisi()
    try:
        seviye, kapsam = etkin_yetki(request, birim_bul(request, BIRIM))
    except Http404:
        seviye, kapsam = 0, None
    y.goruntule, y.yonetim = seviye >= GORUNTULEME, seviye >= YONETIM
    if kapsam == Yetki.BOLUM:
        y.kapsam_bolum = request.user.bolum
        y.yonetim = False  # bölüm hesabı yalnızca görür (PPYS: STS bölüm ekranı salt okunur)
        if y.kapsam_bolum is None:
            y.goruntule = False
    request._puantaj_yetkisi = y
    return y


# ---------------------------------------------------------------- salon amiri kuralı

AMIR_UNVANLARI = {"dröğtüyesi", "doçdr", "profdr"}
AMIR_RUTBELERI = {"bnb", "yb", "alb", "tuğg", "tümg", "korg", "org"}


def _sade(metin):
    return "".join((metin or "").replace(".", " ").split()).replace("İ", "i").casefold()


def amir_olmali(p):
    return (_sade(getattr(p.unvan, "metin", "")) in AMIR_UNVANLARI
            or _sade(getattr(p.rutbe, "metin", "")) in AMIR_RUTBELERI)


def amir_adaylari():
    """Kurala uyan, sınav görevi alan (rolü boş olmayan) ve henüz salon amiri olmayan aktif personel."""
    qs = Personel.objects.filter(aktif=True, sinav_gorevi_alabilir=True).exclude(sinav_rolleri="").select_related("unvan", "rutbe")
    return [p for p in qs if "A" not in p.sinav_rolleri and amir_olmali(p)]


def kurala_gore_amir_ata():
    """Adaylara A rolünü ekler (diğer rolleri değişmez). Dönüş: güncellenen personel sayısı."""
    adaylar = amir_adaylari()
    for p in adaylar:
        p.sinav_rolleri = "".join(r for r in "AGT" if r in p.sinav_rolleri + "A")
        p.save(update_fields=["sinav_rolleri"])
    if adaylar:
        rolleri_esitle()
    return len(adaylar)


# ---------------------------------------------------------------- yıl

def yil_baslangici(tarih):
    return datetime.date(tarih.year if tarih.month >= 10 else tarih.year - 1, 10, 1)


def yil_sonu(bas):
    return datetime.date(bas.year + 1, 9, 30)


def yil_etiketi(bas):
    return f"{bas.year}–{bas.year + 1}"


# ---------------------------------------------------------------- hesap

def puanlar(bas, haric_donem=None):
    """{personel: {"hi", "hs", "puan"}}: yıl içindeki görevler (haric_donem'in işlenmiş görevleri hariç)."""
    qs = SinavGorevi.objects.filter(tarih__range=(bas, yil_sonu(bas)))
    if haric_donem is not None:
        qs = qs.exclude(sinav_donemi=haric_donem)
    out = defaultdict(lambda: {"hi": 0, "hs": 0, "puan": 0.0})
    for pid, tarih in qs.values_list("personel_id", "tarih"):
        o = out[pid]
        if tarih.weekday() >= 5:
            o["hs"] += 1
            o["puan"] += HAFTA_SONU_PUANI
        else:
            o["hi"] += 1
            o["puan"] += 1
    return out


def ders_saatleri(okul):
    """{personel: haftalık ders saati} (programdaki eşleşen öğretmenin yükü; eşleşmeyen yok)."""
    if okul is None:
        return {}
    from timetable.data_views import loads

    yuk = loads(okul)[0]
    return {pid: (yuk.get(t.pk) or (0, 0))[0] for pid, t in ogretmen_eslesmesi(okul).items()}


def z_puanlari(saatler, katilanlar):
    """{personel: z}; ortalama ve popülasyon standart sapması katılanların ders saatinden."""
    degerler = [saatler[p] for p in katilanlar if p in saatler]
    if not degerler:
        return {}, None, None
    ort = sum(degerler) / len(degerler)
    ss = math.sqrt(sum((d - ort) ** 2 for d in degerler) / len(degerler))
    return {p: ((saatler[p] - ort) / ss if ss else 0.0) for p in katilanlar if p in saatler}, ort, ss


def onceki_puanlar(period):
    """Sınav Planlama kancası (settings.SINAV_GOREVLI_PUANI): {öğretmen kimliği: yıl içindeki skor}, bu dönem hariç."""
    eslesme = ogretmen_eslesmesi(period.school)
    if not eslesme:
        return {}
    pu = puanlar(yil_baslangici(period.start_date), haric_donem=period)
    saatler = ders_saatleri(period.school)
    katilanlar = set(Personel.objects.filter(pk__in=eslesme, aktif=True, sinav_gorevi_alabilir=True).exclude(sinav_rolleri="")
                     .values_list("pk", flat=True))
    z, _ort, _ss = z_puanlari(saatler, katilanlar)
    return {t.pk: pu[pid]["puan"] + z.get(pid, 0.0) for pid, t in eslesme.items() if pid in katilanlar}


def tablo(bas, okul, bolum=None):
    """Puantaj tablosu: rolü olan ya da yıl içinde görevi bulunan aktif personel, skoru düşükten yükseğe."""
    pu = puanlar(bas)
    saatler = ders_saatleri(okul)
    qs = Personel.objects.filter(aktif=True).select_related("bolum", "unvan", "rutbe", "sinif")
    tum = [p for p in qs if (p.sinav_rolleri and p.sinav_gorevi_alabilir) or p.pk in pu]
    katilanlar = {p.pk for p in tum if p.sinav_rolleri and p.sinav_gorevi_alabilir and p.pk in saatler}
    z, ort, ss = z_puanlari(saatler, katilanlar)
    satirlar = []
    for p in tum:
        if bolum is not None and p.bolum_id != bolum.pk:
            continue
        o = pu.get(p.pk, {"hi": 0, "hs": 0, "puan": 0.0})
        zp = z.get(p.pk, 0.0)
        satirlar.append({"personel": p, "hi": o["hi"], "hs": o["hs"], "puan": o["puan"], "ders": saatler.get(p.pk),
                         "z": zp, "skor": o["puan"] + zp, "katilir": p.pk in katilanlar})
    satirlar.sort(key=lambda s: (s["skor"], s["personel"].ad_soyad))
    return satirlar, {"ort": ort, "ss": ss, "n": len(katilanlar)}


# ---------------------------------------------------------------- işleme

@transaction.atomic
def isle(period, user):
    """Sınav döneminin görevlerini puantaja yazar (öncekileri değiştirir). Dönüş: (görev sayısı, eşleşmeyen adlar)."""
    from sinav.models import ExamRoom

    from .models import IslenenDonem

    ters = {t.pk: pid for pid, t in ogretmen_eslesmesi(period.school).items()}
    saatler = period.session_times
    SinavGorevi.objects.filter(sinav_donemi=period).delete()
    yeni, eslesmeyen = [], set()
    odalar = (ExamRoom.objects.filter(placement__exam__period=period)
              .select_related("placement__exam__subject", "classroom").prefetch_related("proctors"))
    for room in odalar:
        pl, e = room.placement, room.placement.exam
        for t in room.proctors.all():
            pid = ters.get(t.pk)
            if pid is None:
                eslesmeyen.add(t.full_name)
                continue
            for k in range(max(1, e.duration)):
                s = pl.session + k
                yeni.append(SinavGorevi(
                    personel_id=pid, tarih=pl.date, saat=saatler[s] if s < len(saatler) else "",
                    rol=room.role_of(t.pk), sinav=e.title[:200], salon=str(room.classroom)[:100],
                    donem_adi=period.name[:200], sinav_donemi=period, ekleyen=user))
    SinavGorevi.objects.bulk_create(yeni)
    IslenenDonem.objects.update_or_create(sinav_donemi=period, defaults={"isleyen": user, "gorev_sayisi": len(yeni)})
    return len(yeni), sorted(eslesmeyen)


@transaction.atomic
def geri_al(period):
    from .models import IslenenDonem

    n, _ = SinavGorevi.objects.filter(sinav_donemi=period).delete()
    IslenenDonem.objects.filter(sinav_donemi=period).delete()
    return n


def rolleri_donemden_al(period, ogretmenler=None):
    """Sınav Planlama'nın Gözetmenler sayfasında değiştirilen rolleri personele yazar (roller KAMYOSİS'te tutulur;
    sınav programı oluşturulurken personelden yeniden aktarılır)."""
    degisen = 0
    alamayan = set(Personel.objects.filter(sinav_gorevi_alabilir=False).values_list("pk", flat=True))
    for pid, t in ogretmen_eslesmesi(period.school).items():
        if ogretmenler is not None and t.pk not in ogretmenler:
            continue
        if pid in alamayan:  # dönemde rolsüz görünür; kartındaki roller korunur
            continue
        roller = period.roles_of(t.pk) if period.duty_roles else None
        if roller is None:
            continue
        sayi = Personel.objects.filter(pk=pid).exclude(sinav_rolleri=roller).update(sinav_rolleri=roller)
        degisen += sayi
    return degisen


def rolleri_esitle():
    """Personelin görev rollerini mazeret dönemine bağlı sınav dönemlerine yazar (rol değişikliği hemen geçsin)."""
    from sinav.models import DEFAULT_ROLES, ExamPeriod

    for period in ExamPeriod.objects.filter(mazeret_donemi__isnull=False).select_related("school"):
        eslesme = ogretmen_eslesmesi(period.school)
        roller = dict(period.proctor_roles or {})
        for p in Personel.objects.filter(pk__in=eslesme):  # sınav görevi alamayan: rolsüz (görev verilmez)
            roller[str(eslesme[p.pk].pk)] = p.sinav_rolleri if p.sinav_gorevi_alabilir else ""
        period.proctor_roles = {k: v for k, v in roller.items() if v != DEFAULT_ROLES}
        period.save(update_fields=["proctor_roles"])
