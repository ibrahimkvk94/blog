"""Kurulum sihirbazı (aSc "yeni program sihirbazı" benzeri): sıfırdan başlayan bir kurumu adım adım programa götürür.

Adımlar: başlangıç → program → ders saatleri → ders adları → sınıflar → derslikler → öğretmenler → dersler → kurallar →
kontrol ve üretim. Liste adımlarında kayıtlar Excel'den kopyalanıp yapıştırılarak (sekme ya da ";" ile ayrılmış sütunlar)
toplu eklenir; var olan kayıt aynı adla yeniden yazılırsa güncellenir. Dersler, Excel aktarımının ders sayfasıyla aynı
kurallarla okunur (ders adı ya da kodu, sınıflar, öğretmen kısa adı ya da ad soyadı).
"""

import datetime

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import importer
from .models import Availability, Classroom, Period, School, SchoolClass, Subject, Teacher
from .rooms_wizard import PRACTICAL
from .textsort import natural_key

STEPS = [
    ("baslangic", "Başlangıç", "sparkles"),
    ("program", "Program bilgileri", "settings"),
    ("saatler", "Günler ve ders saatleri", "calendar"),
    ("ders-adlari", "Ders adları", "book"),
    ("siniflar", "Sınıflar", "layers"),
    ("derslikler", "Derslikler", "building"),
    ("ogretmenler", "Öğretmenler", "user"),
    ("dersler", "Dersler", "list"),
    ("kurallar", "Kurallar ve kısıtlar", "link"),
    ("uret", "Kontrol ve üretim", "play"),
]
SLUGS = [s for s, _, _ in STEPS]

# Liste adımları: yapıştırılan sütunlar, örnek satırlar ve açıklama.
PASTE = {
    "ders-adlari": {
        "columns": ["Ad", "Kod (kısa ad)"],
        "example": "Matematik\tMAT101\nTemel Bilgi Teknolojileri\tTBT101\nTemel Bilgi Teknolojileri (U)\tTBT101",
        "help": "Kod, ana görünümde kartın üstünde yazar. Uygulama dersleri adın sonuna “(U)” eklenerek ayrılır.",
    },
    "siniflar": {
        "columns": ["Ad", "Kısa ad", "Öğrenci sayısı"],
        "example": "Bilgisayar Programcılığı 1.KISIM\t1BİL\t35\nBilgisayar Programcılığı 2.KISIM\t2BİL\t32",
        "help": "Sınıf, kısım ya da şube: aynı anda tek ders alan öğrenci topluluğu. Kısa ad ana görünümün satır başlığıdır.",
    },
    "derslikler": {
        "columns": ["Ad", "Kısa ad", "Kapasite", "Bina"],
        "example": "Bilgisayar Laboratuvarı 1\tLAB1\t30\tA Blok\nAmfi 1\tAMF1\t120\tA Blok",
        "help": "Ders dersliği ister ya da ortak kullanılan bir mekânda yapılırsa ekleyin; dersliksiz dersler de üretilir.",
    },
    "ogretmenler": {
        "columns": ["Ad soyad", "Kısa ad", "E-posta", "Haftalık ders yükü"],
        "example": "Ahmet Yılmaz\tAYILMAZ\tahmet@okul.edu.tr\t20\nAyşe Demir\tADEMIR",
        "help": "Ad soyadın son sözcüğü soyad sayılır. E-posta değişiklik ve vekâlet bildirimleri içindir.",
    },
    "dersler": {
        "columns": ["Ders adı ya da kodu", "Sınıflar", "Öğretmenler", "Haftalık saat", "Kart dağılımı"],
        "example": "MAT101\t1BİL, 2BİL\tAYILMAZ\t4\t2+2\nTBT101\t1BİL\tAyşe Demir\t2",
        "help": "Birden çok sınıf ya da öğretmen virgülle yazılır (birleşik ders). Teori ve uygulama aynı kodu taşıyorsa uygulama "
                "“KOD (U)” diye yazılır. Kart dağılımı boşsa ders 1 saatlik kartlara bölünür; "
                "ör. 2+2 haftada iki ayrı 2 saatlik blok demektir.",
    },
}


def _split_line(line):
    sep = "\t" if "\t" in line else ";"
    return [c.strip() for c in line.split(sep)]


def _rows(text, columns):
    """Yapıştırılan metnin satırları → [(satır no, [sütunlar])]; başlık satırı atlanır."""
    rows = []
    for n, line in enumerate((text or "").splitlines(), start=1):
        if not line.strip():
            continue
        cells = (_split_line(line) + [""] * len(columns))[:len(columns)]
        if n == 1 and cells[0].casefold() == columns[0].casefold():
            continue
        rows.append((n, cells))
    return rows


def _int(value):
    value = (value or "").strip()
    return int(value) if value.isdigit() else None


def _add_subjects(school, rows):
    errors, added, updated = [], 0, 0
    count = school.subjects.count()
    for n, (name, short) in rows:
        if not name:
            errors.append(f"{n}. satır: ad boş.")
            continue
        subject, created = Subject.objects.get_or_create(
            school=school, name=name[:100], defaults={"color": importer.PALETTE[(count + added) % len(importer.PALETTE)]})
        if short:
            subject.short = short[:60]
            subject.save(update_fields=["short"])
        added, updated = added + created, updated + (not created)
    return added, updated, errors


def _add_classes(school, rows):
    errors, added, updated = [], 0, 0
    for n, (name, short, students) in rows:
        if not name:
            errors.append(f"{n}. satır: ad boş.")
            continue
        cls, created = SchoolClass.objects.get_or_create(school=school, name=name[:50])
        if short:
            cls.short = short[:30]
        if students:
            if _int(students) is None:
                errors.append(f"{n}. satır: öğrenci sayısı sayı olmalı.")
            else:
                cls.student_count = _int(students)
        cls.save()
        added, updated = added + created, updated + (not created)
    return added, updated, errors


def _add_rooms(school, rows):
    from .models import Building

    errors, added, updated = [], 0, 0
    for n, (name, short, capacity, building) in rows:
        if not name:
            errors.append(f"{n}. satır: ad boş.")
            continue
        if capacity and _int(capacity) is None:
            errors.append(f"{n}. satır: kapasite sayı olmalı.")
            continue
        room, created = Classroom.objects.get_or_create(school=school, name=name[:100])
        if short:
            room.short = short[:60]
        if capacity:
            room.capacity = _int(capacity)
        if building:
            room.building, _ = Building.objects.get_or_create(school=school, name=building[:100])
        room.save()
        added, updated = added + created, updated + (not created)
    return added, updated, errors


def _add_teachers(school, rows):
    errors, added, updated = [], 0, 0
    for n, (full, short, email, load) in rows:
        parts = full.split()
        if not parts:
            errors.append(f"{n}. satır: ad soyad boş.")
            continue
        first, last = (" ".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (parts[0], "")
        if load and _int(load) is None:
            errors.append(f"{n}. satır: haftalık ders yükü sayı olmalı.")
            continue
        if email and "@" not in email:
            errors.append(f"{n}. satır: e-posta geçersiz.")
            continue
        teacher = Teacher.objects.filter(school=school, first_name=first, last_name=last).first()
        created = teacher is None
        if created:
            teacher = Teacher(school=school, first_name=first[:100], last_name=last[:100])
        if short:
            teacher.short = short[:60]
        if email:
            teacher.email = email[:254]
        if load:
            teacher.target_periods = _int(load)
        teacher.save()
        added, updated = added + created, updated + (not created)
    return added, updated, errors


class _PasteImporter(importer._Importer):
    """Excel aktarımının ders okuyucusu, satırları yapıştırılan metinden alır."""

    def __init__(self, school, rows):
        super().__init__(school)
        self.pasted = rows

    def rows(self, wb, title):
        return self.pasted

    def refresh(self):
        super().refresh()
        # Sınıf kısa adı da tanınsın (Excel şablonunda yalnızca ad vardır).
        for c in self.school.classes.all():
            if c.short:
                self.classes.setdefault(importer._key(c.short), c)
        # Teori ve uygulama aynı kodu taşıyabilir: "KOD" teoriyi, "KOD (U)" uygulamayı bulur.
        for subject in self.school.subjects.all():
            if subject.short:
                if PRACTICAL.search(subject.name):
                    self.subjects[importer._key(f"{subject.short} (U)")] = subject
                else:
                    self.subjects[importer._key(subject.short)] = subject


def _add_lessons(school, rows):
    data = [(n, {"Ders adı": subject, "Sınıflar": classes, "Gruplar": "", "Öğretmenler": teachers, "Derslikler": "",
                 "Haftalık saat": hours, "Kart uzunluğu": None, "Günde en fazla": None, "Kart dağılımı": split})
            for n, (subject, classes, teachers, hours, split) in rows]
    imp = _PasteImporter(school, data)
    with transaction.atomic():
        imp.lessons_sheet(None)
        if imp.errors:
            transaction.set_rollback(True)
    counts = imp.counts["Dersler"]
    if imp.errors:
        return 0, 0, [e.replace("Dersler, satır ", "").replace(":", ". satır:", 1) for e in imp.errors]
    return counts["eklenen"], counts["güncellenen"], []


ADDERS = {"ders-adlari": _add_subjects, "siniflar": _add_classes, "derslikler": _add_rooms, "ogretmenler": _add_teachers,
          "dersler": _add_lessons}


def make_periods(school, count, start, length, short_break, lunch_after, lunch):
    """Ders saatlerini üretir: var olanlar sıra numarasıyla güncellenir, fazlası silinir."""
    current = datetime.datetime.combine(datetime.date.today(), start)
    existing = {p.index: p for p in school.periods.all()}
    with transaction.atomic():
        for i in range(count):
            end = current + datetime.timedelta(minutes=length)
            period = existing.get(i) or Period(school=school, index=i)
            period.name, period.start_time, period.end_time = f"{i + 1}. saat", current.time(), end.time()
            period.long_break_after = lunch_after == i + 1
            period.day_times = {}
            period.save()
            current = end + datetime.timedelta(minutes=lunch if i + 1 == lunch_after else short_break)
        school.periods.filter(index__gte=count).delete()


def status(school):
    """Adım → (sayı, tamam mı, kısa durum)."""
    n = {
        "saatler": school.periods.count(), "ders-adlari": school.subjects.count(), "siniflar": school.classes.count(),
        "derslikler": school.classrooms.count(), "ogretmenler": school.teachers.count(), "dersler": school.lessons.count(),
        "kurallar": school.relationships.count(),
    }
    hours = sum(school.lessons.values_list("periods_per_week", flat=True))
    out = {
        "baslangic": (None, True, ""),
        "program": (None, bool(school.name), f"{school.days_per_week} gün"),
        "saatler": (n["saatler"], n["saatler"] > 0, f"{school.days_per_week} gün × {n['saatler']} saat"),
        "ders-adlari": (n["ders-adlari"], n["ders-adlari"] > 0, f"{n['ders-adlari']} ders adı"),
        "siniflar": (n["siniflar"], n["siniflar"] > 0, f"{n['siniflar']} sınıf"),
        "derslikler": (n["derslikler"], True, f"{n['derslikler']} derslik" if n["derslikler"] else "isteğe bağlı"),
        "ogretmenler": (n["ogretmenler"], n["ogretmenler"] > 0, f"{n['ogretmenler']} öğretmen"),
        "dersler": (n["dersler"], n["dersler"] > 0, f"{n['dersler']} ders · {hours} saat"),
        "kurallar": (n["kurallar"], True, f"{n['kurallar']} ilişki" if n["kurallar"] else "isteğe bağlı"),
        "uret": (None, school.timetables.exists(), "program üretildi" if school.timetables.exists() else ""),
    }
    return out


def _existing(school, slug):
    if slug == "ders-adlari":
        items = [(s.short or s.name, s.name if s.short else "") for s in school.subjects.all()]
    elif slug == "siniflar":
        items = [(c.short or c.name, c.name if c.short else "") for c in school.classes.all()]
    elif slug == "derslikler":
        items = [(r.short or r.name, r.name if r.short else "") for r in school.classrooms.all()]
    elif slug == "ogretmenler":
        items = [(t.short or t.full_name, t.full_name if t.short else "") for t in school.teachers.all()]
    elif slug == "dersler":
        lessons = school.lessons.select_related("subject").prefetch_related("classes", "teachers")
        items = [(f"{l.subject.short or l.subject.name} · {', '.join(c.short or c.name for c in l.classes.all()) or '—'}",
                  f"{l.periods_per_week} saat · {', '.join(t.full_name for t in l.teachers.all()) or 'öğretmensiz'}") for l in lessons]
    else:
        return []
    return sorted(items, key=lambda i: natural_key(i[0]))


EDIT_LINKS = {
    "ders-adlari": ("timetable:data_list", "ders-adlari"), "siniflar": ("timetable:data_list", "siniflar"),
    "derslikler": ("timetable:data_list", "derslikler"), "ogretmenler": ("timetable:data_list", "ogretmenler"),
    "dersler": ("timetable:lessons", None),
}


def wizard(request, pk, step="baslangic"):
    from . import forms
    from .services import check_school
    from .views import _nav

    school = get_object_or_404(School, pk=pk)
    if step not in SLUGS:
        step = "baslangic"
    index = SLUGS.index(step)
    url = lambda s: reverse("timetable:setup_wizard", args=[school.pk, s])  # noqa: E731
    form = None
    if step == "program":
        form = forms.SchoolForm(request.POST or None, instance=school)
    if request.method == "POST":
        action = request.POST.get("action", "")
        if step == "program" and form.is_valid():
            form.save()
            messages.success(request, "Program bilgileri kaydedildi.")
            return redirect(url(SLUGS[index + 1]))
        if step == "saatler":
            try:
                make_periods(
                    school, count=max(1, min(16, int(request.POST.get("count") or 8))),
                    start=datetime.time.fromisoformat(request.POST.get("start") or "08:30"),
                    length=max(10, min(240, int(request.POST.get("length") or 40))),
                    short_break=max(0, min(120, int(request.POST.get("break") or 10))),
                    lunch_after=int(request.POST.get("lunch_after") or 0), lunch=max(0, min(180, int(request.POST.get("lunch") or 60))),
                )
            except ValueError:
                messages.error(request, "Saat bilgilerini sayı ve SS:DD biçiminde girin.")
                return redirect(url(step))
            messages.success(request, "Ders saatleri oluşturuldu.")
            return redirect(url(SLUGS[index + 1]))
        if step in PASTE and action == "paste":
            rows = _rows(request.POST.get("text"), PASTE[step]["columns"])
            if not rows:
                messages.warning(request, "Eklenecek satır yok.")
                return redirect(url(step))
            added, updated, errors = ADDERS[step](school, rows)
            for e in errors[:12]:
                messages.error(request, e)
            if errors:
                if step == "dersler":
                    messages.warning(request, "Dersler eklenmedi: önce satırlardaki hataları düzeltin (hiçbir satır kaydedilmedi).")
                request.session[f"setup-{school.pk}-{step}"] = request.POST.get("text", "")
            else:
                request.session.pop(f"setup-{school.pk}-{step}", None)
            if added or updated:
                messages.success(request, f"{added} kayıt eklendi" + (f", {updated} kayıt güncellendi" if updated else "") + ".")
            return redirect(url(step))
        return redirect(url(step))

    st = status(school)
    steps = [{"slug": s, "title": t, "icon": i, "url": url(s), "count": st[s][0], "done": st[s][1], "note": st[s][2],
              "current": s == step, "number": n} for n, (s, t, i) in enumerate(STEPS)]
    context = {
        "steps": steps, "step": steps[index], "prev": steps[index - 1] if index else None,
        "next": steps[index + 1] if index + 1 < len(steps) else None, "form": form,
        "progress": round(100 * sum(1 for s in steps[1:] if s["done"]) / (len(steps) - 1)),
    }
    if step in PASTE:
        name, arg = EDIT_LINKS[step]
        context.update(paste=PASTE[step], existing=_existing(school, step),
                       draft=request.session.get(f"setup-{school.pk}-{step}", ""),
                       edit_url=reverse(name, args=[school.pk] + ([arg] if arg else [])))
    if step == "saatler":
        periods = list(school.periods.all())
        first = periods[0] if periods else None
        context.update(periods=periods, defaults={
            "count": len(periods) or 8, "start": first.start_time.strftime("%H:%M") if first and first.start_time else "08:30",
            "length": (datetime.datetime.combine(datetime.date.today(), first.end_time) - datetime.datetime.combine(datetime.date.today(), first.start_time)).seconds // 60
            if first and first.start_time and first.end_time else 40,
            "lunch_after": next((p.index + 1 for p in periods if p.long_break_after), 0) if periods else 4,
        }, has_timetables=school.timetables.exists())
    if step == "kurallar":
        context.update(relations=school.relationships.count(),
                       unavailable=Availability.objects.filter(school=school, teacher__isnull=False).values("teacher").distinct().count())
    if step == "uret":
        issues = check_school(school) if school.lessons.exists() else []
        context.update(issues=issues, errors=sum(1 for i in issues if i.level == "error"),
                       hours=sum(school.lessons.values_list("periods_per_week", flat=True)),
                       slots=school.days_per_week * school.periods.count(), timetables=school.timetables.count())
    return render(request, "timetable/setup_wizard.html", _nav(school, "kurulum", **context))
