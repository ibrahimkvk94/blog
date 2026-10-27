"""Veritabanındaki okul verisini çözücünün Problem yapısına çevirir."""

from collections import defaultdict

from ..models import Availability
from .problem import (
    Problem,
    ProblemCard,
    RelationshipSpec,
    TeacherLimits,
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
    return index


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
    all_cells = [(d, p) for d in range(days) for p in range(periods)]

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
    class_students = {cls.id: cls.student_count for cls in classes}
    room_capacity = {r.id: r.capacity for r in school.classrooms.all()}
    group_students = {}
    for cls in classes:
        for division in cls.divisions.all():
            for group in division.groups.all():
                group_students[group.id] = group.student_count

    lesson_data = {}
    for lesson in lessons:
        class_ids = [c.id for c in lesson.classes.all()]
        teacher_ids = tuple(t.id for t in lesson.teachers.all())
        rooms = tuple(r.id for r in lesson.classrooms.all())
        if not rooms and len(class_ids) == 1 and home_room.get(class_ids[0]):
            rooms = (home_room[class_ids[0]],)
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
        if students and rooms:
            fitting = tuple(r for r in rooms if room_capacity.get(r) is None or room_capacity[r] >= students)
            if not fitting:
                label = f"{lesson.subject} – {', '.join(c.name for c in lesson.classes.all())}"
                notes.append(("error", "room_capacity", f"{label}: {students} öğrenci hiçbir seçili dersliğe sığmıyor."))
            else:
                rooms = fitting
        entities = [("teacher", t) for t in teacher_ids]
        entities += [("school_class", c) for c in class_ids]
        entities += [("subject", lesson.subject_id), ("lesson", lesson.id)]
        if len(rooms) == 1:
            entities.append(("classroom", rooms[0]))
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
            "universes": card_universes(
                lesson.weeks_mask, lesson.terms_mask, school.weeks_count, school.terms_count
            ),
            "states": states,
            "maybe": frozenset(c for c, s in states.items() if s == Availability.MAYBE),
            "label": f"{lesson.subject} – {', '.join(c.name for c in lesson.classes.all())}",
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
            universes=data["universes"],
            starts=starts_for(lesson_id, length),
            maybe_slots=data["maybe"],
            blocked=blocked_for(lesson_id, length),
        )
        if db_card is not None:
            card.card_id = db_card.id
            if db_card.is_placed:
                card.hint = (db_card.day, db_card.period, db_card.classroom_id)
                if db_card.locked:
                    card.fixed = (db_card.day, db_card.period)
                    card.fixed_room = db_card.classroom_id
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

    def free_cells(entity):
        return sum(1 for cell in all_cells if avail.get(entity, {}).get(cell) != Availability.NO)

    room_blocked = {
        r.id: frozenset(c for c, s in avail.get(("classroom", r.id), {}).items() if s == Availability.NO)
        for r in school.classrooms.all()
    }

    atom_available = {}
    for cls in classes:
        free = free_cells(("school_class", cls.id))
        for atom_id in atoms_by_class[cls.id]:
            atom_available[atom_id] = free

    class_limits = {
        cls.id: (cls.min_periods_per_day, cls.max_periods_per_day)
        for cls in classes
        if cls.min_periods_per_day is not None or cls.max_periods_per_day is not None
    }
    grades = {cls.id: cls.grade for cls in classes}
    return Problem(
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
        teacher_available={t.id: free_cells(("teacher", t.id)) for t in teachers},
        atom_available=atom_available,
        labels={
            "lesson": {lid: d["label"] for lid, d in lesson_data.items()},
            "teacher": {t.id: t.full_name for t in teachers},
            "class": {c.id: c.name for c in classes},
            "atom": labels_atom,
            "room": {r.id: str(r) for r in school.classrooms.all()},
            "entity": {
                **{("teacher", t.id): f"{t.full_name} (öğretmen)" for t in teachers},
                **{("school_class", c.id): f"{c.name} (sınıf)" for c in classes},
                **{("subject", sub.id): f"{sub.name} (ders adı)" for sub in school.subjects.all()},
                **{("classroom", r.id): f"{r} (derslik)" for r in school.classrooms.all()},
                **{("lesson", lid): f"{d['label']} (ders)" for lid, d in lesson_data.items()},
            },
        },
    )


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

        groups_b = []
        if rel.condition in rel.PAIRED:
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
            if two_sided:
                keys = [k for k in by_owner if k in by_owner_b]
                groups = [by_owner[k] for k in keys]
                groups_b = [by_owner_b[k] for k in keys]
            else:
                groups = list(by_owner.values())
        if not groups:
            continue
        specs.append(
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
            )
        )
    return specs
