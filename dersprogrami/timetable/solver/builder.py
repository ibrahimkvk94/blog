"""Veritabanındaki okul verisini çözücünün Problem yapısına çevirir."""

from collections import defaultdict
from dataclasses import replace

from ..models import Availability
from .problem import (
    Problem,
    ProblemCard,
    RelationshipSpec,
    TeacherLimits,
    TeacherPool,
    card_universes,
    class_atoms,
    lesson_atoms,
)


def _availability_index(school):
    index = defaultdict(dict)
    for a in school.availabilities.all():
        for field in Availability.TARGET_FIELDS:
            target_id = getattr(a, field + "_id")
            if target_id:
                index[(field, target_id)][(a.day, a.period)] = a.state
                break
        else:
            index[("school", school.id)][(a.day, a.period)] = a.state
    return index


def _norm(name):
    return " ".join(str(name or "").casefold().split())


def linked_busy(school):
    """Birlikte çalışan programların yayındaki programında dolu öğretmen/derslik hücreleri.

    Programlar ayrı veri tuttuğu için eşleştirme ada göre yapılır: öğretmen ad soyadı, derslik adı.
    Dönüş: {("teacher", id) | ("classroom", id): {(gün, saat), ...}}
    """
    busy = defaultdict(set)
    linked = list(school.linked_programs.all()) if school.pk else []
    if not linked:
        return busy
    teachers = {_norm(t.full_name): t.id for t in school.teachers.all()}
    rooms = {_norm(r.name): r.id for r in school.classrooms.all()}
    for other in linked:
        timetable = other.active_timetable or other.timetables.filter(status__in=["ok", "partial"]).first()
        if timetable is None:
            continue
        other_rooms = {r.id: _norm(r.name) for r in other.classrooms.all()}
        for card in timetable.cards.filter(day__isnull=False).prefetch_related("lesson__teachers"):
            cells = {(card.day, card.period + i) for i in range(card.length)}
            for t in card.lesson.teachers.all():
                if _norm(t.full_name) in teachers:
                    busy[("teacher", teachers[_norm(t.full_name)])] |= cells
            for room_id in card.room_ids:
                if other_rooms.get(room_id) in rooms:
                    busy[("classroom", rooms[other_rooms[room_id]])] |= cells
    return busy


def lesson_label(lesson):
    classes = ", ".join(c.name for c in lesson.classes.all())
    if classes:
        return f"{lesson.subject} – {classes}"
    teachers = ", ".join(t.full_name for t in lesson.teachers.all())
    return f"{lesson.subject} – {teachers or 'sınıfsız'}"


def lesson_rooms(lesson, subject_rooms, teacher_home, class_home):
    """Dersin olası derslikleri: dersin kendi seçimi → ders adının varsayılanları → öğretmen dersliği
    (tek öğretmenliyse) → sınıf dersliği (tek sınıflıysa; birden çok derslik isteyen birleşik derslerde
    tüm sınıfların derslikleri)."""
    rooms = tuple(r.id for r in lesson.classrooms.all())
    if rooms:
        return rooms
    if subject_rooms.get(lesson.subject_id):
        return subject_rooms[lesson.subject_id]
    teachers = [t.id for t in lesson.teachers.all()]
    if len(teachers) == 1 and teacher_home.get(teachers[0]):
        return (teacher_home[teachers[0]],)
    homes = [class_home[c.id] for c in lesson.classes.all() if class_home.get(c.id)]
    if len(homes) == 1 or (homes and lesson.rooms_needed > 1):
        return tuple(dict.fromkeys(homes))
    return ()


def _match_base_cards(sources, base):
    """Derslerden türetilen kartları temel sürümün kartlarıyla eşler (önce kilitliler, sonra yerleşmişler)."""
    pool = defaultdict(list)
    for card in base.cards.order_by("-locked", "id"):
        if card.is_placed:
            pool[(card.lesson_id, card.length)].append(card)
    matched = []
    for lesson_id, length, _ in sources:
        candidates = pool.get((lesson_id, length))
        matched.append((lesson_id, length, candidates.pop(0) if candidates else None))
    return matched


def build_problem(school, timetable=None, base=None):
    """Okul verisinden Problem üretir.

    timetable: kartlar bu programın kart satırlarından birebir alınır (doğrulama için).
    base: kartlar güncel derslerden türetilir; temel sürümdeki aynı ders ve uzunluktaki kartların
        kilidi (sabit yer) ve konumu (ipucu) yeni kartlara aktarılır.
    İkisi de verilmezse kartlar derslerin haftalık saatlerinden türetilir.
    """
    days = school.days_per_week
    period_rows = list(school.periods.all())
    periods = len(period_rows)
    # Ardından uzun teneffüs olan saatler: blok kartlar bu sınırın üzerinden geçemez.
    breaks = {p.index for p in period_rows if p.long_break_after}
    notes = []
    all_universes = card_universes(None, None, school.weeks_count, school.terms_count)
    avail = _availability_index(school)
    # Aynı anda yürüyen (bağlı) programlarda dolu olan öğretmen/derslik saatleri burada kapalıdır.
    for entity, cells in linked_busy(school).items():
        for cell in cells:
            avail[entity][cell] = Availability.NO
    all_cells = [(d, p) for d in range(days) for p in range(periods)]

    school_entity = ("school", school.id)

    def cell_state(entities, cell):
        states = {avail.get(e, {}).get(cell) for e in entities}
        if Availability.NO in states:
            return Availability.NO
        if Availability.MAYBE in states:
            return Availability.MAYBE
        return None

    classes = list(school.classes.prefetch_related("divisions__groups"))
    atoms_by_class, class_of_group, labels_atom = {}, {}, {}
    group_names = {}
    for cls in classes:
        divisions = []
        for division in cls.divisions.all():
            ids = []
            for group in division.groups.all():
                ids.append(group.id)
                class_of_group[group.id] = cls.id
                group_names[group.id] = group.name
            divisions.append(ids)
        atoms_by_class[cls.id] = class_atoms(cls.id, divisions)
        for atom_id, groups in atoms_by_class[cls.id].items():
            suffix = " ".join(group_names[g] for g in sorted(groups))
            labels_atom[atom_id] = f"{cls.name} {suffix}".strip()

    lessons = list(
        school.lessons.select_related("subject").prefetch_related("classes", "groups", "teachers", "classrooms")
    )
    home_room = {cls.id: cls.home_classroom_id for cls in classes}
    subject_rooms = defaultdict(tuple)
    for subject in school.subjects.prefetch_related("classrooms"):
        subject_rooms[subject.id] = tuple(r.id for r in subject.classrooms.all())
    teacher_names = {t.id: t.full_name for t in school.teachers.all()}
    teacher_home = {t.id: t.home_classroom_id for t in school.teachers.all() if t.home_classroom_id}
    qualified = {t.id: {s.id for s in t.subjects.all()} for t in school.teachers.prefetch_related("subjects")}
    class_students = {cls.id: cls.student_count for cls in classes}
    room_capacity = {r.id: r.capacity for r in school.classrooms.all()}
    group_students = {}
    for cls in classes:
        for division in cls.divisions.all():
            for group in division.groups.all():
                group_students[group.id] = group.student_count

    # Öğretmen havuzları (yalnızca üretimde; kaydedilmiş bir program doğrulanırken dersin öğretmeni geçerlidir)
    pools, pooled = [], set()
    if timetable is None:
        pools, notes_pools = _teacher_pools(school, lessons, avail)
        notes += notes_pools
        pooled = {lesson_id for pool in pools for lesson_id in pool.lessons}

    lesson_data = {}
    for lesson in lessons:
        class_ids = [c.id for c in lesson.classes.all()]
        # Havuzdaki dersin öğretmeni çözücüde seçilir: sabit öğretmeni ve onun müsaitliği yok
        teacher_ids = () if lesson.id in pooled else tuple(t.id for t in lesson.teachers.all())
        label = lesson_label(lesson)
        rooms = lesson_rooms(lesson, subject_rooms, teacher_home, home_room)
        needed = max(1, lesson.rooms_needed)
        # Derslik kapasitesi: öğrenci sayısı biliniyorsa sığmayan derslikler seçenekten çıkar.
        lesson_groups = list(lesson.groups.all())
        students = 0
        for class_id in class_ids:
            chosen = [g for g in lesson_groups if class_of_group.get(g.id) == class_id]
            counts = [group_students.get(g.id) for g in chosen] if chosen else [class_students.get(class_id)]
            if any(c is None for c in counts):
                students = None
                break
            students += sum(counts)
        if students and rooms and needed == 1:
            fitting = tuple(r for r in rooms if room_capacity.get(r) is None or room_capacity[r] >= students)
            if not fitting:
                notes.append(("error", "room_capacity", f"{label}: {students} öğrenci hiçbir seçili dersliğe sığmıyor."))
            else:
                rooms = fitting
        if needed > 1 and len(rooms) < needed:
            notes.append(
                ("error", "rooms_needed", f"{label}: {needed} derslik gerekiyor, ancak yalnızca {len(rooms)} olası derslik var.")
            )
        for t in teacher_ids:
            if qualified.get(t) and lesson.subject_id not in qualified[t]:
                notes.append(("warning", "out_of_branch", f"{label}: {teacher_names[t]} bu dersin branşında değil."))
        entities = [("teacher", t) for t in teacher_ids]
        entities += [("school_class", c) for c in class_ids]
        entities += [("subject", lesson.subject_id), ("lesson", lesson.id), school_entity]
        if rooms and len(rooms) <= needed:
            entities += [("classroom", r) for r in rooms]
        states = {cell: cell_state(entities, cell) for cell in all_cells}
        lesson_data[lesson.id] = {
            "entities": entities,
            "subject": lesson.subject_id,
            "classes": class_ids,
            "teachers": teacher_ids,
            "atoms": lesson_atoms(
                class_ids, [g.id for g in lesson.groups.all()], atoms_by_class, class_of_group
            ),
            "rooms": rooms,
            "rooms_needed": min(needed, len(rooms)) if rooms else 1,
            "universes": card_universes(
                lesson.weeks_mask, lesson.terms_mask, school.weeks_count, school.terms_count
            ),
            "states": states,
            "maybe": frozenset(c for c, s in states.items() if s == Availability.MAYBE),
            "label": label,
        }

    def crosses_break(p, length):
        return any(p + i in breaks for i in range(length - 1))

    def starts_for(lesson_id, length):
        states = lesson_data[lesson_id]["states"]
        return [
            (d, p)
            for d in range(days)
            for p in range(periods - length + 1)
            if not crosses_break(p, length) and all(states[(d, p + i)] != Availability.NO for i in range(length))
        ]

    def blocked_for(lesson_id, length):
        """Yalnızca müsaitlik yüzünden kapalı başlangıçlar → kapatan varlıklar (açıklama modu için)."""
        entities = lesson_data[lesson_id]["entities"]
        blocked = {}
        for d in range(days):
            for p in range(periods - length + 1):
                if crosses_break(p, length):
                    continue
                culprits = frozenset(
                    e for e in entities for i in range(length) if avail.get(e, {}).get((d, p + i)) == Availability.NO
                )
                if culprits:
                    blocked[(d, p)] = culprits
        return blocked

    if timetable is not None:
        sources = [
            (card.lesson_id, card.length, card)
            for card in timetable.cards.order_by("lesson_id", "id")
            if card.lesson_id in lesson_data
        ]
    else:
        sources = [(lesson.id, length, None) for lesson in lessons for length in lesson.card_lengths()]

    if base is not None:
        sources = _match_base_cards(sources, base)

    from ..students import solver_student_keys

    student_keys = solver_student_keys(school)
    cards = []
    for key, (lesson_id, length, db_card) in enumerate(sources):
        data = lesson_data[lesson_id]
        card = ProblemCard(
            key=key,
            lesson_id=lesson_id,
            length=length,
            teachers=data["teachers"],
            atoms=data["atoms"],
            room_options=data["rooms"],
            rooms_needed=data["rooms_needed"],
            universes=data["universes"],
            starts=starts_for(lesson_id, length),
            maybe_slots=data["maybe"],
            blocked=blocked_for(lesson_id, length),
            students=student_keys.get(lesson_id, ()),
            subject=data["subject"],
        )
        if db_card is not None:
            card.card_id = db_card.id
            if db_card.is_placed:
                card.hint = (db_card.day, db_card.period, db_card.classroom_id)
                if db_card.locked:
                    card.fixed = (db_card.day, db_card.period)
                    card.fixed_room = db_card.classroom_id
                    card.fixed_rooms = tuple(db_card.room_ids)
        cards.append(card)

    teachers = list(school.teachers.all())
    day_names = school.day_names
    for t in teachers:
        cells = avail.get(("teacher", t.id), {})
        for d in range(days):
            free = sum(1 for p in range(periods) if cells.get((d, p)) != Availability.NO)
            if 0 < free <= 2 and periods >= 5 and free < periods:
                notes.append(
                    (
                        "warning",
                        "mostly_blocked_day",
                        f"{t.full_name}: {day_names[d]} günü yalnızca {free} saat açık. Bu bilinçli değilse günü tamamen "
                        "kapatmak ya da açmak üretimi kolaylaştırır.",
                    )
                )
    teacher_limits = {
        t.id: TeacherLimits(
            t.max_periods_per_day, t.max_gaps_per_day, t.max_gaps_per_week, t.max_days_per_week,
            t.max_consecutive, t.min_periods_per_day,
        )
        for t in teachers
    }

    lesson_card_count = defaultdict(int)
    for card in cards:
        lesson_card_count[card.lesson_id] += 1
    lesson_max_per_day = {}
    for lesson in lessons:
        n = lesson_card_count[lesson.id]
        lesson_max_per_day[lesson.id] = lesson.max_per_day or max(1, -(-n // days))

    school_closed = {c for c, s in avail.get(school_entity, {}).items() if s == Availability.NO}

    def free_cells(entity):
        return sum(
            1 for cell in all_cells if cell not in school_closed and avail.get(entity, {}).get(cell) != Availability.NO
        )

    room_blocked = {
        r.id: frozenset(c for c, s in avail.get(("classroom", r.id), {}).items() if s == Availability.NO)
        for r in school.classrooms.all()
    }

    atom_available = {}
    for cls in classes:
        free = free_cells(("school_class", cls.id))
        for atom_id in atoms_by_class[cls.id]:
            atom_available[atom_id] = free

    notes += _advisor_notes(school, classes, lessons, lesson_data, cards, avail, days, periods, school_closed)

    class_limits = {
        cls.id: (cls.min_periods_per_day, cls.max_periods_per_day)
        for cls in classes
        if cls.min_periods_per_day is not None or cls.max_periods_per_day is not None
    }
    grades = {cls.id: cls.grade for cls in classes}
    return Problem(
        teacher_pools=pools,
        relationships=_relationships(school, cards, lesson_data, grades),
        class_limits=class_limits,
        room_building={r.id: r.building_id for r in school.classrooms.all() if r.building_id},
        notes=notes,
        days=days,
        periods=periods,
        universes=all_universes,
        cards=cards,
        teacher_limits=teacher_limits,
        lesson_max_per_day=lesson_max_per_day,
        room_blocked=room_blocked,
        room_slots={r.id: r.max_lessons for r in school.classrooms.all() if r.max_lessons > 1},
        teacher_available={t.id: free_cells(("teacher", t.id)) for t in teachers},
        atom_available=atom_available,
        labels={
            "lesson": {lid: d["label"] for lid, d in lesson_data.items()},
            "teacher": {t.id: t.full_name for t in teachers},
            "class": {c.id: c.name for c in classes},
            "atom": labels_atom,
            "students": {k: "Seçmeli dersleri ortak öğrenciler" for keys in student_keys.values() for k in keys},
            "room": {r.id: str(r) for r in school.classrooms.all()},
            "entity": {
                school_entity: "Okul geneli kapalı saatler",
                **{("teacher", t.id): f"{t.full_name} (öğretmen)" for t in teachers},
                **{("school_class", c.id): f"{c.name} (sınıf)" for c in classes},
                **{("subject", sub.id): f"{sub.name} (ders adı)" for sub in school.subjects.all()},
                **{("classroom", r.id): f"{r} (derslik)" for r in school.classrooms.all()},
                **{("lesson", lid): f"{d['label']} (ders)" for lid, d in lesson_data.items()},
            },
        },
    )


def _teacher_pools(school, lessons, avail):
    """Ders adı başına öğretmen kotalarından havuzlar. Kilitli (öğretmeni sabit) kısımlar öğretmeninin
    kotasından düşer; kalan kısımların öğretmenini çözücü seçer. Kotalar tutmazsa hata notu döner ve o ders
    adının kısımları şu anki öğretmenleriyle kalır."""
    from ..models import TeacherQuota

    quotas = defaultdict(dict)
    for subject_id, teacher_id, count in TeacherQuota.objects.filter(school=school).values_list("subject_id", "teacher_id", "count"):
        if count:
            quotas[subject_id][teacher_id] = count
    if not quotas:
        return [], []
    by_subject = defaultdict(list)
    for lesson in lessons:
        by_subject[lesson.subject_id].append(lesson)
    pools, notes = [], []
    for subject_id, quota in quotas.items():
        sections = [l for l in by_subject.get(subject_id, []) if len(l.teachers.all()) <= 1]
        if not sections:
            continue
        name = sections[0].subject.short or sections[0].subject.name
        remaining = dict(quota)
        free = []
        for lesson in sections:
            current = lesson.teachers.all()[0].id if lesson.teachers.all() else None
            if lesson.teacher_locked and current is not None:
                if current in remaining:
                    remaining[current] -= 1
            else:
                free.append(lesson)
        over = [t for t, n in remaining.items() if n < 0]
        if over or sum(remaining.values()) != len(free):
            locked = len(sections) - len(free)
            notes.append(("error", "teacher_pool", f"{name} öğretmen kotaları tutmuyor: kotaların toplamı {sum(quota.values())}, "
                          f"kısım sayısı {len(sections)} ({locked} sabit). Öğretmen atama sayfasında kotaları düzeltin."))
            continue
        remaining = {t: n for t, n in remaining.items() if n > 0}
        if not free or not remaining:
            continue
        closed = {t: frozenset(c for c, state in avail.get(("teacher", t), {}).items() if state == Availability.NO) for t in remaining}
        hints = {l.id: l.teachers.all()[0].id for l in free if l.teachers.all() and l.teachers.all()[0].id in remaining}
        pools.append(TeacherPool(name=name, lessons=tuple(l.id for l in free), quotas=remaining, closed=closed, hints=hints))
    return pools, notes


def _advisor_notes(school, classes, lessons, lesson_data, cards, avail, days, periods, school_closed):
    """aSc "Danışman" uyarıları (kılavuz 25.6–25.12): veri büyük olasılıkla hatalı ya da eksik."""
    notes = []
    group_hours = defaultdict(int)
    group_lengths = defaultdict(list)
    for lesson in lessons:
        for group in lesson.groups.all():
            group_hours[group.id] += lesson.periods_per_week
            group_lengths[group.id] += lesson.card_lengths()
    for cls in classes:
        for division in cls.divisions.all():
            groups = list(division.groups.all())
            if not any(group_hours.get(g.id) for g in groups):
                continue
            hours = {g.name: group_hours.get(g.id, 0) for g in groups}
            if len(set(hours.values())) > 1:
                detail = ", ".join(f"{name} {h} saat" for name, h in hours.items())
                notes.append(("warning", "group_hours", f"{cls.name} / {division.name}: grupların haftalık saati farklı ({detail}). "
                              "Gruplar aynı saatte ders görmezse sınıf programında boşluk oluşur."))
            elif len({tuple(sorted(group_lengths.get(g.id, []))) for g in groups}) > 1:
                notes.append(("warning", "group_lengths", f"{cls.name} / {division.name}: grupların kart uzunlukları farklı "
                              "(ör. birinde blok, diğerinde tekil ders). Gruplar aynı saatlere oturamaz; boşluk oluşabilir."))

    # Dersliği girilmemiş ders sınıfın kendi dersliğinde yapılır: uyarı gerekmez.

    if classes:
        for p in range(periods):
            closed = all(
                (d, p) in school_closed or avail.get(("school_class", cls.id), {}).get((d, p)) == Availability.NO
                for cls in classes
                for d in range(days)
            )
            if closed and any(c.atoms for c in cards):
                notes.append(("warning", "closed_period", f"{p + 1}. saat hiçbir sınıf için hiçbir gün açık değil. "
                              "Bilinçli değilse sınıf ya da okul müsaitliklerini kontrol edin."))

    class_hours = defaultdict(int)
    for card in cards:
        for class_id in {Problem.atom_class(a) for a in card.atoms}:
            class_hours[class_id] += card.length
    for cls in classes:
        hours = class_hours.get(cls.id, 0)
        if cls.max_periods_per_day and hours > cls.max_periods_per_day * days:
            notes.append(("error", "class_max_total", f"{cls.name}: haftada {hours} saat ders var, günde en fazla "
                          f"{cls.max_periods_per_day} sınırıyla en çok {cls.max_periods_per_day * days} saat sığar."))
        if cls.min_periods_per_day and hours < cls.min_periods_per_day * days:
            notes.append(("error", "class_min_total", f"{cls.name}: haftada yalnızca {hours} saat ders var, günde en az "
                          f"{cls.min_periods_per_day} kuralı için {cls.min_periods_per_day * days} saat gerekir."))
    return notes


def _parse_map(raw):
    cells = set()
    for item in raw or []:
        try:
            d, p = (int(x) for x in str(item).split("-"))
        except ValueError:
            continue
        cells.add((d, p))
    return frozenset(cells) or None


def _relationships(school, cards, lesson_data, grades):
    specs = []
    relationships = school.relationships.filter(active=True).prefetch_related(
        "lessons", "subjects", "lessons_b", "subjects_b", "classes", "teachers", "classrooms"
    )
    for rel in relationships:
        if rel.condition in rel.STUDENT:  # seçmeli dağıtımında uygulanır
            continue
        class_filter = {c.id for c in rel.classes.all()}
        teacher_filter = {t.id for t in rel.teachers.all()}

        def side(lesson_ids, subject_ids):
            def selected(card):
                data = lesson_data[card.lesson_id]
                if (lesson_ids or subject_ids) and card.lesson_id not in lesson_ids and data["subject"] not in subject_ids:
                    return False
                if class_filter and not class_filter & set(data["classes"]):
                    return False
                if teacher_filter and not teacher_filter & set(data["teachers"]):
                    return False
                if rel.card_length and card.length != rel.card_length:
                    return False
                return True

            return [c for c in cards if selected(c)]

        lesson_ids = [lesson.id for lesson in rel.lessons.all()]
        chosen = side(lesson_ids, {s.id for s in rel.subjects.all()})
        two_sided = rel.condition in rel.TWO_SIDED
        chosen_b = side([lesson.id for lesson in rel.lessons_b.all()], {s.id for s in rel.subjects_b.all()}) if two_sided else []
        if not chosen or (two_sided and not chosen_b):
            continue

        def owners(card):
            data = lesson_data[card.lesson_id]
            classes = [c for c in data["classes"] if not class_filter or c in class_filter]
            teachers = [t for t in data["teachers"] if not teacher_filter or t in teacher_filter]
            mode = rel.apply_to
            if mode == rel.ALL:
                return [None]
            if mode == rel.EACH_CLASS:
                return classes
            if mode == rel.EACH_TEACHER:
                return teachers
            if mode == rel.EACH_SUBJECT_CLASS:
                return [(data["subject"], c) for c in classes]
            if mode == rel.EACH_TEACHER_CLASS:
                return [(t, c) for t in teachers for c in classes]
            if mode == rel.EACH_GROUP:
                return [a for a in card.atoms if not class_filter or Problem.atom_class(a) in class_filter]
            if mode == rel.EACH_GRADE:
                return sorted({grades.get(c) for c in classes}, key=str)
            return [None]

        groups_b, owner_refs = [], []
        if rel.condition == rel.RESERVE:
            # Rezerv: seçilen dersler bir küme; aynı sınıfların seçilmeyen kartları işaretli saatlere giremez.
            chosen_keys = {c.key for c in chosen}
            classes = {cl for c in chosen for cl in lesson_data[c.lesson_id]["classes"] if not class_filter or cl in class_filter}
            others = [c.key for c in cards if c.key not in chosen_keys and classes & set(lesson_data[c.lesson_id]["classes"])]
            groups, groups_b = [sorted(chosen_keys)], [others]
        elif rel.condition in rel.PAIRED:
            order = lesson_ids or sorted({c.lesson_id for c in chosen})
            groups = [[c.key for c in chosen if c.lesson_id == lid] for lid in order]
            groups = [g for g in groups if g]
        else:
            by_owner, by_owner_b = defaultdict(list), defaultdict(list)
            for card in chosen:
                for owner in owners(card):
                    by_owner[owner].append(card.key)
            for card in chosen_b:
                for owner in owners(card):
                    by_owner_b[owner].append(card.key)
            keys = [k for k in by_owner if k in by_owner_b] if two_sided else list(by_owner)
            groups = [by_owner[k] for k in keys]
            if two_sided:
                groups_b = [by_owner_b[k] for k in keys]
            kind = {rel.EACH_TEACHER: "teacher", rel.EACH_CLASS: "class"}.get(rel.apply_to)
            owner_refs = [(kind, k) if kind else None for k in keys]
        if not groups:
            continue
        spec = (
            RelationshipSpec(
                rel.name,
                rel.condition,
                rel.param,
                groups,
                rel.weight,
                _parse_map(rel.time_map) if rel.condition in rel.USES_MAP else None,
                rel.id,
                groups_b,
                _parse_map(rel.time_map_b) if two_sided else None,
                tuple(r.id for r in rel.classrooms.all()),
                owner_refs,
            )
        )
        if rel.condition in rel.SOFT_TARGET and rel.param_max is not None and rel.param_max > rel.param:
            # N tercih edilen sınır (aşımı cezalı), param_max hiç aşılamayan istisna sınırı.
            specs.append(replace(spec, name=f"{rel.name} (istisna sınırı {rel.param_max})", param=rel.param_max, weight=None))
            spec = replace(spec, name=f"{rel.name} (tercih {rel.param})", weight=rel.weight or rel.WEIGHTS[rel.HIGH])
        specs.append(spec)
    return specs
