"""KAMYOSİS: program oluştuktan sonra görev değişikliği (PPYS SPS "personel değiştir / takas et").

- Başka öğretmene verme: görev aynı rolle yeni öğretmene geçer.
- Takas: iki görevin öğretmenleri yer değiştirir (her biri diğerinin rolünü alır).
- Uygunluk: öğretmen o oturumda başka salonda görevli olmamalı, gelemeyeceği oturum (müsaitlik / mazeret ✗) ve
  muafiyet olmamalı, rol kuralı açıksa rolü alabilmeli. "Mümkünse verilmesin" (?) engel değil, uyarıdır.
- Gerekçe zorunludur; her değişiklik ExamDutyChange olarak kaydedilir. Değişen sınavın yerleşimi kilitlenir:
  program yeniden oluşturulsa da yeri, salonları ve görevlileri korunur.
"""

from collections import defaultdict

from django.db import transaction

from timetable.models import Teacher

from . import services as exams
from .models import GOZETMEN, ROLE_NAMES, ExamDutyChange, ExamRoom


class DegisiklikHatasi(Exception):
    pass


def _oturumlar(pl):
    return {(pl.date, pl.session + k) for k in range(max(1, pl.exam.duration))}


def _odalar(period):
    return list(ExamRoom.objects.filter(placement__exam__period=period)
                .select_related("placement__exam__subject", "classroom").prefetch_related("proctors")
                .order_by("placement__date", "placement__session", "classroom__name"))


class Baglam:
    """Dönemin görevleri ve uygunluk bilgisi (bir istek boyunca)."""

    def __init__(self, period):
        self.period = period
        self.odalar = _odalar(period)
        self.oda = {r.pk: r for r in self.odalar}
        self.blocks = exams.proctor_blocks(period)
        self.soft = exams.proctor_soft(period)
        self.exempt = set(period.proctor_exempt.values_list("pk", flat=True))
        self.dolu = defaultdict(dict)   # öğretmen → {(tarih, oturum): salon kimliği}
        self.yuk = defaultdict(int)
        for r in self.odalar:
            for t in r.proctors.all():
                self.yuk[t.pk] += 1
                for o in _oturumlar(r.placement):
                    self.dolu[t.pk][o] = r.pk

    def gorevler(self):
        """[(anahtar, salon, öğretmen, rol)] tarih sırasıyla."""
        out = []
        for r in self.odalar:
            for t, rol, _ad in r.duties:
                out.append((f"{r.pk}:{t.pk}", r, t, rol))
        return out

    def bul(self, anahtar):
        try:
            rid, tid = (int(x) for x in str(anahtar).split(":"))
        except ValueError:
            raise DegisiklikHatasi("Görev bulunamadı; sayfayı yenileyin.") from None
        r = self.oda.get(rid)
        t = next((t for t in r.proctors.all() if t.pk == tid), None) if r else None
        if t is None:
            raise DegisiklikHatasi("Görev bulunamadı ya da bu sırada değişti; sayfayı yenileyin.")
        return r, t, r.role_of(t.pk) if self.period.duty_roles else GOZETMEN

    def sorunlar(self, ogretmen_id, oda, rol, birakilan=()):
        """Öğretmen bu salonda bu rolle görev alabilir mi: (engeller, uyarılar). birakilan: aynı işlemde bırakacağı
        salonlar (takasta kendi görevi)."""
        engel, uyari = [], []
        oturumlar = _oturumlar(oda.placement)
        if ogretmen_id in {t.pk for t in oda.proctors.all()} and oda.pk not in birakilan:
            engel.append("bu salonda zaten görevli")
        cakisan = {self.dolu[ogretmen_id].get(o) for o in oturumlar} - {None, *birakilan}
        if cakisan:
            r = self.oda[next(iter(cakisan))]
            engel.append(f"aynı anda {r.classroom} salonunda görevli")
        if oturumlar & self.blocks.get(ogretmen_id, set()):
            engel.append("gelemeyeceği oturum")
        if ogretmen_id in self.exempt:
            engel.append("muaf")
        if self.period.duty_roles and rol not in self.period.roles_of(ogretmen_id):
            engel.append(f"{ROLE_NAMES.get(rol, rol).lower()} olamaz")
        if oturumlar & self.soft.get(ogretmen_id, set()):
            uyari.append("mümkünse verilmesin demiş")
        return engel, uyari

    def adaylar(self, anahtar):
        """Görevi alabilecek öğretmenler: [{"teacher", "engel", "uyari", "yuk"}], uygun ve yükü az olan önce."""
        oda, eski, rol = self.bul(anahtar)
        out = []
        for t in Teacher.objects.filter(school=self.period.school_id):
            if t.pk == eski.pk:
                continue
            engel, uyari = self.sorunlar(t.pk, oda, rol)
            out.append({"teacher": t, "engel": engel, "uyari": uyari, "yuk": self.yuk[t.pk]})
        out.sort(key=lambda a: (bool(a["engel"]), bool(a["uyari"]), a["yuk"], a["teacher"].last_name))
        return out

    def takaslar(self, anahtar):
        """Bu görevle takas edilebilecek görevler: [{"anahtar", "oda", "teacher", "rol", "uyari"}]."""
        oda1, t1, rol1 = self.bul(anahtar)
        out = []
        for k, oda2, t2, rol2 in self.gorevler():
            if t2.pk == t1.pk or oda2.pk == oda1.pk:
                continue
            e1, u1 = self.sorunlar(t1.pk, oda2, rol2, birakilan=(oda1.pk,))
            e2, u2 = self.sorunlar(t2.pk, oda1, rol1, birakilan=(oda2.pk,))
            if not e1 and not e2:
                out.append({"anahtar": k, "oda": oda2, "teacher": t2, "rol": rol2,
                            "uyari": [f"{t1.full_name}: {x}" for x in u1] + [f"{t2.full_name}: {x}" for x in u2]})
        return out


def etiket(oda, period):
    pl = oda.placement
    return f"{exams.slot_label(pl.date, pl.session, period)} · {pl.exam.title} · {oda.classroom}"


def _yaz(oda, cikan, giren, rol):
    oda.proctors.remove(cikan)
    oda.proctors.add(giren)
    roller = dict(oda.roles or {})
    roller.pop(str(cikan.pk), None)
    if rol != GOZETMEN:
        roller[str(giren.pk)] = rol
    oda.roles = roller
    oda.save(update_fields=["roles"])
    pl = oda.placement
    if not pl.locked:
        pl.locked = True
        pl.save(update_fields=["locked"])


def _gerekce(metin):
    metin = (metin or "").strip()
    if not metin:
        raise DegisiklikHatasi("Gerekçe yazın.")
    return metin[:200]


@transaction.atomic
def baskasina_ver(period, anahtar, yeni_id, user, gerekce):
    gerekce = _gerekce(gerekce)
    b = Baglam(period)
    oda, eski, rol = b.bul(anahtar)
    yeni = Teacher.objects.filter(school=period.school_id, pk=yeni_id).first()
    if yeni is None:
        raise DegisiklikHatasi("Yeni öğretmeni seçin.")
    engel, _ = b.sorunlar(yeni.pk, oda, rol)
    if engel:
        raise DegisiklikHatasi(f"{yeni.full_name} bu görevi alamaz: {', '.join(engel)}.")
    _yaz(oda, eski, yeni, rol)
    ozet = f"{etiket(oda, period)} · {ROLE_NAMES.get(rol, rol)}: {eski.full_name} → {yeni.full_name}"
    return ExamDutyChange.objects.create(period=period, kind=ExamDutyChange.REPLACE, summary=ozet, reason=gerekce, user=user)


@transaction.atomic
def takas(period, anahtar1, anahtar2, user, gerekce):
    gerekce = _gerekce(gerekce)
    b = Baglam(period)
    oda1, t1, rol1 = b.bul(anahtar1)
    oda2, t2, rol2 = b.bul(anahtar2)
    if anahtar2 not in {x["anahtar"] for x in b.takaslar(anahtar1)}:
        raise DegisiklikHatasi("Bu iki görev takas edilemez (çakışma, müsaitlik ya da rol uymuyor).")
    _yaz(oda1, t1, t2, rol1)
    oda2.refresh_from_db()
    _yaz(oda2, t2, t1, rol2)
    ozet = (f"Takas: {t1.full_name} ({etiket(oda1, period)}) ↔ {t2.full_name} ({etiket(oda2, period)})")
    return ExamDutyChange.objects.create(period=period, kind=ExamDutyChange.SWAP, summary=ozet, reason=gerekce, user=user)
