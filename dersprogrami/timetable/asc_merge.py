"""aSc TimeTables XML'i var olan bir programın üzerine "güncelleyerek" aktarma.

"Yerine aktar" programı silip dosyadan yeniden kurar; elle girilen her şey (ÜYBS referansları,
müsaitlikler, öğretmen sınırları, kart ilişkileri, sürümler, yayın ayarları, nöbetler …) kaybolur.
Güncelleyerek aktarmada dosya önce geçici bir programa okunur (``asc_xml.import_school``), sonra
kayıtlar hedef programdakilerle eşleştirilip yalnızca aSc'den gelen alanlar güncellenir; geçici
program en sonda silinir. Her şey tek veritabanı işleminde yapılır: hata olursa hiçbir şey değişmez.

Eşleştirme (büyük/küçük harf, Türkçe İ/ı ve fazladan boşluk fark etmez):
- ders saatleri: sırasına göre (ad ve saatler güncellenir, eksikler eklenir);
- ders adları: kısa ada, yoksa ada göre;
- öğretmenler: kısa ada, yoksa ad soyada göre;
- binalar: ada; derslikler: ada, yoksa kısa ada göre;
- sınıflar: kısa ada, yoksa ada göre; gruplar: aynı sınıfta grup adına göre (bölünmenin adı korunur);
- dersler: (ders adı, sınıflar kümesi, gruplar kümesi); birden çok aday varsa öğretmen kümesi aynı
  olan, yoksa en çok ortak öğretmeni olan seçilir. Eşleşen ders kimliğini (pk) korur; böylece ÜYBS
  referansları, kart ilişkileri ve ders müsaitlikleri yerinde kalır.

Güncellenen alanlar yalnızca aSc'nin taşıdıklarıdır: adlar ve kısa adlar, ders saati zamanları,
derslik kapasitesi ve binası, sınıf seviyesi, sınıf dersliği ve sınıf öğretmeni; derslerde haftalık
saat, kart uzunluğu, hafta/dönem maskeleri, öğretmenler ve derslikler. İsteğe bağlı alanlarda
(saat, kapasite, bina, seviye, sınıf dersliği, sınıf öğretmeni) dosyadaki boş değer mevcut değeri
silmez: aSc dosyalarında bu alanlar çoğu zaman doldurulmaz. Ders adı renkleri korunur (dosyada renk
yoksa içe aktarıcı rastgele renk atar). Diğer her alan (öğretmen sınırları, öğretmen dersliği,
branşlar, nöbet ayarları, öğrenci sayıları, derslik eşzamanlı ders sınırı …) olduğu gibi kalır;
yalnızca kartlarda aynı anda birden çok ders görülen dersliğin sınırı gerekirse yükseltilir.

Dosyada olmayan kayıtlar:
- dersler silinir (kartları ve ÜYBS referanslarıyla; silinen referans sayısı özette yazar). Sınıfı
  olmayan dersler (ör. zümre toplantısı) aSc XML'den okunamadığı için hiç silinmez;
- haftalık saati azalan derslerin yeni saat sayısını aşan ÜYBS referansları silinir;
- ders adı, öğretmen, sınıf, grup, derslik ve binalar yalnızca kalan hiçbir kayıt onları
  kullanmıyorsa silinir: ders adı/sınıf/grup için kalan dersler; öğretmen için kalan dersler ve
  devamsızlık (vekâlet) kayıtları; derslik için kalan dersler, herhangi bir sürümdeki kartlar,
  ders adı varsayılan derslikleri, öğretmen ve sınıf derslikleri; bina için derslikler. Silinmeyenler
  özette "korundu" olarak listelenir. Bölünmesinin bütün grupları silinen bölünme de silinir;
- fazla ders saatleri, herhangi bir sürümde kart kullanmıyorsa silinir.

Kartlar: dosyadaki yerleşim hedef programda yeni bir sürüm ("aSc güncelleme <tarih>") olarak açılır;
var olan sürümler silinmez ve yayındaki program değiştirilmez.

Ders müsaitlikleri: dosyada güne bağlı ders (daysdef) varsa o dersin müsaitliği dosyadakiyle
değiştirilir; dosyada gün kısıtı olmayan derslerin elle girilmiş müsaitliği korunur (kendi aSc
dışa aktarımımız her derse "herhangi bir gün" yazdığı için aksi her aktarmada onları silerdi).
Öğretmen, sınıf, derslik ve ders adı müsaitlikleri, kart ilişkileri, nöbetler, kullanıcı yetkileri
ve yayın ayarlarına dokunulmaz.
"""

from collections import Counter, defaultdict

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from . import asc_xml
from .models import (
    Absence,
    Availability,
    Building,
    Card,
    Classroom,
    Division,
    Group,
    Lesson,
    LessonRef,
    Period,
    SchoolClass,
    Subject,
    Teacher,
    Timetable,
)

KINDS = [
    ("periods", "ders saatleri"),
    ("subjects", "ders adları"),
    ("teachers", "öğretmenler"),
    ("buildings", "binalar"),
    ("classrooms", "derslikler"),
    ("classes", "sınıflar"),
    ("groups", "gruplar"),
    ("lessons", "dersler"),
]


def _norm(value):
    text = (value or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    return " ".join(text.split())


def _match(incoming, existing, keys):
    """Gelen kayıtları var olanlarla eşleştirir: {gelen pk: var olan kayıt}.

    keys: (gelen anahtar, var olan anahtar) işlevleri; sırayla denenir (ör. önce kısa ad, sonra ad).
    Her var olan kayıt en fazla bir gelen kayıtla eşleşir."""
    matched, used = {}, set()
    for in_key, ex_key in keys:
        index = defaultdict(list)
        for obj in existing:
            key = _norm(ex_key(obj))
            if key and obj.pk not in used:
                index[key].append(obj)
        for item in incoming:
            key = _norm(in_key(item))
            if item.pk in matched or not key:
                continue
            for candidate in index.get(key, []):
                if candidate.pk not in used:
                    matched[item.pk] = candidate
                    used.add(candidate.pk)
                    break
    return matched


def _clone(obj, **overrides):
    data = {f.attname: getattr(obj, f.attname) for f in obj._meta.concrete_fields if not f.primary_key}
    data.update(overrides)
    return type(obj).objects.create(**data)


def _update(obj, values, keep_empty=()):
    """Değişen alanları kaydeder; keep_empty'deki alanlarda boş gelen değer mevcut değeri silmez."""
    changed = []
    for field, value in values.items():
        if field in keep_empty and value in (None, ""):
            continue
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(obj._meta.get_field(field).name)
    if changed:
        obj.save(update_fields=changed)
    return bool(changed)


def _new_summary():
    summary = {kind: {"added": 0, "updated": 0, "matched": 0, "removed": 0, "removed_names": [], "kept": []} for kind, _ in KINDS}
    summary["refs_dropped"] = 0
    summary["timetable"] = None
    return summary


@transaction.atomic
def merge_into(school, data):
    """aSc XML'ini ``school`` programının üzerine güncelleyerek aktarır.

    Dönüş: (yeni sürüm ya da None, özet). Özet her tür için {"added", "updated", "matched",
    "removed", "removed_names", "kept"} ile "refs_dropped" (silinen ÜYBS referansı) ve "timetable"
    (yeni sürümün adı) içerir. Dosya okunamazsa ``asc_xml.AscImportError`` yükselir ve hiçbir şey
    değişmez. Kurallar modül açıklamasındadır."""
    temp, temp_timetable = asc_xml.import_school(data, name=f"{school.name} (geçici aktarım)", institution=school.institution)
    merger = _Merger(school, temp)
    merger.run()
    timetable = merger.cards(temp_timetable)
    merger.cleanup()
    temp.delete()
    from .problem_cache import bump

    bump(school.pk)  # ana görünümdeki problem önbelleği yenilensin
    return timetable, merger.summary


class _Merger:
    def __init__(self, school, temp):
        self.school, self.temp = school, temp
        self.summary = _new_summary()
        self.buildings, self.rooms, self.subjects, self.teachers = {}, {}, {}, {}
        self.classes, self.groups, self.lessons = {}, {}, {}

    def _sync(self, kind, incoming, existing, keys, values, keep_empty=(), create=None):
        """Ortak eşleştir-güncelle-ekle döngüsü. values(gelen) → güncellenecek alanlar;
        create(gelen) → yeni kayıt. Dönüş: {gelen pk: hedef kayıt}."""
        matched = _match(incoming, existing, keys)
        result = {}
        stats = self.summary[kind]
        for item in incoming:
            current = matched.get(item.pk)
            if current is None:
                result[item.pk] = create(item)
                stats["added"] += 1
            else:
                stats["matched"] += 1
                if _update(current, values(item), keep_empty):
                    stats["updated"] += 1
                result[item.pk] = current
        return result

    def _pk(self, mapping, key):
        obj = mapping.get(key)
        return obj.pk if obj is not None else None

    def run(self):
        school, temp = self.school, self.temp
        # Ders saatleri: sıraya göre.
        current = {p.index: p for p in school.periods.all()}
        stats = self.summary["periods"]
        self.period_count = 0
        for p in temp.periods.all():
            self.period_count += 1
            existing = current.get(p.index)
            if existing is None:
                _clone(p, school_id=school.id)
                stats["added"] += 1
                continue
            stats["matched"] += 1
            if _update(existing, {"name": p.name, "start_time": p.start_time, "end_time": p.end_time}, {"start_time", "end_time"}):
                stats["updated"] += 1

        self.buildings = self._sync(
            "buildings", list(temp.buildings.all()), list(school.buildings.all()),
            [(lambda b: b.name, lambda b: b.name)],
            lambda b: {"name": b.name},
            create=lambda b: _clone(b, school_id=school.id),
        )

        def room_values(r):
            return {"name": r.name, "short": r.short, "capacity": r.capacity, "building_id": self._pk(self.buildings, r.building_id)}

        incoming_rooms = list(temp.classrooms.all())
        self.rooms = self._sync(
            "classrooms", incoming_rooms, list(school.classrooms.all()),
            [(lambda r: r.name, lambda r: r.name), (lambda r: r.short, lambda r: r.short)],
            room_values, {"short", "capacity", "building_id"},
            create=lambda r: _clone(r, school_id=school.id, building_id=self._pk(self.buildings, r.building_id)),
        )
        for r in incoming_rooms:  # kartlardan çıkarılan eşzamanlı ders sınırı yalnızca yükseltilir
            target = self.rooms[r.pk]
            if r.max_lessons > target.max_lessons:
                target.max_lessons = r.max_lessons
                target.save(update_fields=["max_lessons"])

        self.subjects = self._sync(
            "subjects", list(temp.subjects.all()), list(school.subjects.all()),
            [(lambda s: s.short, lambda s: s.short), (lambda s: s.name, lambda s: s.name)],
            lambda s: {"name": s.name, "short": s.short}, {"short"},
            create=lambda s: _clone(s, school_id=school.id),
        )

        self.teachers = self._sync(
            "teachers", list(temp.teachers.all()), list(school.teachers.all()),
            [(lambda t: t.short, lambda t: t.short), (lambda t: t.full_name, lambda t: t.full_name)],
            lambda t: {"first_name": t.first_name, "last_name": t.last_name, "short": t.short}, {"short"},
            create=lambda t: _clone(t, school_id=school.id, home_classroom_id=None),
        )

        def class_values(c):
            return {
                "name": c.name, "short": c.short, "grade": c.grade,
                "home_classroom_id": self._pk(self.rooms, c.home_classroom_id),
                "class_teacher_id": self._pk(self.teachers, c.class_teacher_id),
            }

        name, short = (lambda c: c.name), (lambda c: c.short)
        self.classes = self._sync(
            "classes", list(temp.classes.all()), list(school.classes.all()),
            [(short, short), (name, name), (name, short), (short, name)],
            class_values, {"grade", "home_classroom_id", "class_teacher_id"},
            create=lambda c: _clone(c, school_id=school.id, **{k: v for k, v in class_values(c).items() if k.endswith("_id")}),
        )

        self._sync_groups()
        self._sync_lessons()

    def _sync_groups(self):
        stats = self.summary["groups"]
        used = set()
        for division in Division.objects.filter(school_class__school=self.temp).prefetch_related("groups").order_by("id"):
            target_class = self.classes[division.school_class_id]
            incoming = list(division.groups.all())
            candidates = [g for g in Group.objects.filter(division__school_class=target_class) if g.pk not in used]
            matched = _match(incoming, candidates, [(lambda g: g.name, lambda g: g.name)])
            owners = Counter(g.division_id for g in matched.values())
            if owners:
                target_division = Division.objects.get(pk=owners.most_common(1)[0][0])
            else:
                target_division = Division.objects.create(school_class=target_class, name=division.name)
            for g in incoming:
                current = matched.get(g.pk)
                if current is None:
                    current = _clone(g, division_id=target_division.id)
                    stats["added"] += 1
                else:
                    stats["matched"] += 1
                    if _update(current, {"name": g.name, "student_count": g.student_count}, {"student_count"}):
                        stats["updated"] += 1
                used.add(current.pk)
                self.groups[g.pk] = current

    def _sync_lessons(self):
        stats = self.summary["lessons"]
        incoming = list(self.temp.lessons.prefetch_related("classes", "groups", "teachers", "classrooms", "availabilities"))
        existing = list(self.school.lessons.prefetch_related("classes", "groups", "teachers", "classrooms").order_by("id"))

        def key_in(lesson):
            return (
                self.subjects[lesson.subject_id].pk,
                frozenset(self.classes[c.pk].pk for c in lesson.classes.all()),
                frozenset(self.groups[g.pk].pk for g in lesson.groups.all()),
            )

        def teachers_in(lesson):
            return frozenset(self.teachers[t.pk].pk for t in lesson.teachers.all())

        def key_ex(lesson):
            return (lesson.subject_id, frozenset(c.pk for c in lesson.classes.all()), frozenset(g.pk for g in lesson.groups.all()))

        def teachers_ex(lesson):
            return frozenset(t.pk for t in lesson.teachers.all())

        by_key = defaultdict(list)
        for lesson in existing:
            by_key[key_ex(lesson)].append(lesson)
        matched, used = {}, set()
        for lesson in incoming:  # 1. tur: öğretmenleri de aynı olan
            for candidate in by_key[key_in(lesson)]:
                if candidate.pk not in used and teachers_ex(candidate) == teachers_in(lesson):
                    matched[lesson.pk] = candidate
                    used.add(candidate.pk)
                    break
        for lesson in incoming:  # 2. tur: en çok ortak öğretmeni olan
            if lesson.pk in matched:
                continue
            candidates = [c for c in by_key[key_in(lesson)] if c.pk not in used]
            if candidates:
                best = max(candidates, key=lambda c: (len(teachers_ex(c) & teachers_in(lesson)), -c.pk))
                matched[lesson.pk] = best
                used.add(best.pk)

        for lesson in incoming:
            teachers = [self.teachers[t.pk] for t in lesson.teachers.all()]
            rooms = [self.rooms[r.pk] for r in lesson.classrooms.all()]
            availability = list(lesson.availabilities.all())
            target = matched.get(lesson.pk)
            if target is None:
                target = _clone(lesson, school_id=self.school.id, subject_id=self.subjects[lesson.subject_id].pk)
                target.classes.set([self.classes[c.pk] for c in lesson.classes.all()])
                target.groups.set([self.groups[g.pk] for g in lesson.groups.all()])
                target.teachers.set(teachers)
                target.classrooms.set(rooms)
                stats["added"] += 1
            else:
                stats["matched"] += 1
                changed = _update(target, {
                    "periods_per_week": lesson.periods_per_week, "card_length": lesson.card_length,
                    "weeks_mask": lesson.weeks_mask, "terms_mask": lesson.terms_mask,
                })
                if teachers_ex(target) != {t.pk for t in teachers}:
                    target.teachers.set(teachers)
                    changed = True
                if {r.pk for r in target.classrooms.all()} != {r.pk for r in rooms}:
                    target.classrooms.set(rooms)
                    changed = True
                if availability:
                    old = {(a.day, a.period, a.state) for a in target.availabilities.all()}
                    if old != {(a.day, a.period, a.state) for a in availability}:
                        target.availabilities.all().delete()
                        changed = True
                    else:
                        availability = []
                stats["updated"] += changed
                dropped, _ = LessonRef.objects.filter(lesson=target, ordinal__gt=target.periods_per_week).delete()
                self.summary["refs_dropped"] += dropped
            Availability.objects.bulk_create(
                Availability(school=self.school, lesson=target, day=a.day, period=a.period, state=a.state) for a in availability
            )
            self.lessons[lesson.pk] = target

        # Dosyada olmayan dersler silinir; sınıfsız dersler aSc XML'den okunamadığı için korunur.
        removed = [lesson for lesson in existing if lesson.pk not in used and lesson.classes.all()]
        if removed:
            stats["removed"] = len(removed)
            stats["removed_names"] = [str(lesson) for lesson in removed]
            self.summary["refs_dropped"] += LessonRef.objects.filter(lesson__in=removed).count()
            Lesson.objects.filter(pk__in=[lesson.pk for lesson in removed]).delete()

    def cards(self, temp_timetable):
        if temp_timetable is None:
            return None
        name = f"aSc güncelleme {timezone.localtime():%d.%m.%Y %H:%M}"
        timetable = Timetable.objects.create(school=self.school, name=name, status=temp_timetable.status, mode=temp_timetable.mode)
        Card.objects.bulk_create(
            Card(
                timetable=timetable, lesson=self.lessons[c.lesson_id], length=c.length, day=c.day, period=c.period,
                classroom=self.rooms.get(c.classroom_id), extra_rooms=[self.rooms[r].pk for r in c.extra_rooms or [] if r in self.rooms],
                locked=c.locked,
            )
            for c in temp_timetable.cards.all()
        )
        from .versions import save_version

        save_version(timetable, note="aSc'den güncellenerek aktarıldı", auto=True)
        self.summary["timetable"] = timetable.name
        return timetable

    def _remove(self, kind, queryset, in_use, label=str):
        """Dosyada olmayan kayıtlar: kullanılmıyorsa silinir, kullanılıyorsa korunur."""
        stats = self.summary[kind]
        doomed = []
        for obj in queryset:
            if obj.pk in in_use:
                stats["kept"].append(label(obj))
            else:
                doomed.append(obj.pk)
                stats["removed_names"].append(label(obj))
        if doomed:
            queryset.model.objects.filter(pk__in=doomed).delete()
            stats["removed"] += len(doomed)

    def cleanup(self):
        school = self.school
        lessons = Lesson.objects.filter(school=school)
        through = Lesson.classes.through

        def mapped(mapping):
            return {obj.pk for obj in mapping.values()}

        self._remove(
            "subjects", school.subjects.exclude(pk__in=mapped(self.subjects)),
            set(lessons.values_list("subject_id", flat=True)),
        )
        self._remove(
            "classes", school.classes.exclude(pk__in=mapped(self.classes)),
            set(through.objects.filter(lesson__school=school).values_list("schoolclass_id", flat=True)),
        )
        teachers_in_use = set(Lesson.teachers.through.objects.filter(lesson__school=school).values_list("teacher_id", flat=True))
        teachers_in_use |= set(Absence.objects.filter(school=school).values_list("teacher_id", flat=True))
        self._remove("teachers", school.teachers.exclude(pk__in=mapped(self.teachers)), teachers_in_use, label=lambda t: t.full_name)

        # Gruplar: yalnızca dosyadaki sınıflarda, dosyada olmayan ve hiçbir dersin kullanmadığı gruplar.
        groups = Group.objects.filter(division__school_class__in=mapped(self.classes)).exclude(pk__in=mapped(self.groups))
        divisions = set(groups.values_list("division_id", flat=True))
        self._remove(
            "groups", groups.select_related("division__school_class"),
            set(Lesson.groups.through.objects.filter(lesson__school=school).values_list("group_id", flat=True)),
        )
        Division.objects.filter(pk__in=divisions, groups__isnull=True).delete()

        cards = Card.objects.filter(timetable__school=school)
        rooms_in_use = set(Lesson.classrooms.through.objects.filter(lesson__school=school).values_list("classroom_id", flat=True))
        for room, extra in cards.values_list("classroom_id", "extra_rooms"):
            rooms_in_use.add(room)
            rooms_in_use.update(extra or [])
        rooms_in_use |= set(Subject.classrooms.through.objects.filter(subject__school=school).values_list("classroom_id", flat=True))
        rooms_in_use |= set(Teacher.objects.filter(school=school).values_list("home_classroom_id", flat=True))
        rooms_in_use |= set(SchoolClass.objects.filter(school=school).values_list("home_classroom_id", flat=True))
        self._remove("classrooms", school.classrooms.exclude(pk__in=mapped(self.rooms)), rooms_in_use)
        self._remove(
            "buildings", school.buildings.exclude(pk__in=mapped(self.buildings)),
            set(Classroom.objects.filter(school=school).values_list("building_id", flat=True)),
        )

        # Fazla ders saatleri: kart kullanmıyorsa (sondan) silinir.
        last_used = max(
            (period + length - 1 for period, length in cards.filter(period__isnull=False).values_list("period", "length")),
            default=-1,
        )
        keep_until = max(last_used, self.period_count - 1)
        extra = school.periods.filter(index__gte=self.period_count)
        self._remove("periods", extra, set(extra.filter(index__lte=keep_until).values_list("pk", flat=True)))
        Availability.objects.filter(school=school, period__gt=keep_until).delete()

        # Gün/hafta/dönem sayısı dosyadan; gün sayısı var olan sürümlerdeki kartların gerektirdiğinden az olamaz.
        last_day = cards.aggregate(day=Max("day"))["day"]
        days = max(self.temp.days_per_week, (last_day + 1) if last_day is not None else 0)
        _update(school, {"days_per_week": days, "weeks_count": self.temp.weeks_count, "terms_count": self.temp.terms_count})


def describe(summary):
    """Özetin Türkçe tek satırlık açıklaması (başarı mesajı için)."""
    parts = []
    for kind, label in KINDS:
        stats = summary[kind]
        bits = []
        if stats["added"]:
            bits.append(f"{stats['added']} eklendi")
        if stats["updated"]:
            bits.append(f"{stats['updated']} güncellendi")
        if stats["removed"]:
            bits.append(f"{stats['removed']} silindi")
        if stats["kept"]:
            shown = ", ".join(stats["kept"][:5]) + (" …" if len(stats["kept"]) > 5 else "")
            bits.append(f"{len(stats['kept'])} dosyada yok ama kullanıldığı için korundu ({shown})")
        if bits:
            parts.append(f"{label} {', '.join(bits)}")
    text = "; ".join(parts) if parts else "veride değişiklik yok"
    text = text[0].upper() + text[1:] + "."
    if summary["refs_dropped"]:
        text += f" {summary['refs_dropped']} ÜYBS referansı silindi (silinen ya da saati azalan dersler)."
    if summary["timetable"]:
        text += f" Dosyadaki yerleşim yeni sürüm olarak açıldı: “{summary['timetable']}” (yayındaki program değişmedi)."
    return text
