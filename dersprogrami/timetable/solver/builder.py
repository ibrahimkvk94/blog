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
    periods = school.periods.count()
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

    lesson_data = {}
    for lesson in lessons:
        class_ids = [c.id for c in lesson.classes.all()]
        teacher_ids = tuple(t.id for t in lesson.teachers.all())
        rooms = tuple(r.id for r in lesson.classrooms.all())
        if not rooms and len(class_ids) == 1 and home_room.get(class_ids[0]):
            rooms = (home_room[class_ids[0]],)
        entities = [("teacher", t) for t in teacher_ids]
        entities += [("school_class", c) for c in class_ids]
        entities += [("subject", lesson.subject_id), ("lesson", lesson.id)]
        if len(rooms) == 1:
            entities.append(("classroom", rooms[0]))
        states = {cell: cell_state(entities, cell) for cell in all_cells}
        lesson_data[lesson.id] = {
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

    def starts_for(lesson_id, length):
        states = lesson_data[lesson_id]["states"]
        return [
            (d, p)
            for d in range(days)
            for p in range(periods - length + 1)
            if all(states[(d, p + i)] != Availability.NO for i in range(length))
        ]

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
    teacher_limits = {
        t.id: TeacherLimits(t.max_periods_per_day, t.max_gaps_per_day, t.max_gaps_per_week, t.max_days_per_week)
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

    return Problem(
        relationships=_relationships(school, cards, lesson_data),
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
            "teacher": {t.id: str(t) for t in teachers},
            "atom": labels_atom,
            "room": {r.id: str(r) for r in school.classrooms.all()},
        },
    )


def _relationships(school, cards, lesson_data):
    specs = []
    relationships = school.relationships.filter(active=True).prefetch_related(
        "lessons", "subjects", "classes", "teachers"
    )
    for rel in relationships:
        lesson_ids = [lesson.id for lesson in rel.lessons.all()]
        subject_ids = {subject.id for subject in rel.subjects.all()}
        class_filter = {c.id for c in rel.classes.all()}
        teacher_filter = {t.id for t in rel.teachers.all()}

        def selected(lesson_id):
            data = lesson_data[lesson_id]
            if (lesson_ids or subject_ids) and lesson_id not in lesson_ids and data["subject"] not in subject_ids:
                return False
            if class_filter and not class_filter & set(data["classes"]):
                return False
            if teacher_filter and not teacher_filter & set(data["teachers"]):
                return False
            return True

        chosen = [c for c in cards if selected(c.lesson_id)]
        if not chosen:
            continue
        if rel.condition == rel.SAME_TIME:
            order = lesson_ids or sorted({c.lesson_id for c in chosen})
            groups = [[c.key for c in chosen if c.lesson_id == lid] for lid in order]
            groups = [g for g in groups if g]
        elif rel.apply_to == rel.ALL:
            groups = [[c.key for c in chosen]]
        else:
            attr = "classes" if rel.apply_to == rel.EACH_CLASS else "teachers"
            limit_to = class_filter if attr == "classes" else teacher_filter
            by_owner = defaultdict(list)
            for card in chosen:
                for owner in lesson_data[card.lesson_id][attr]:
                    if not limit_to or owner in limit_to:
                        by_owner[owner].append(card.key)
            groups = list(by_owner.values())
        specs.append(RelationshipSpec(rel.name, rel.condition, rel.param, groups, rel.weight))
    return specs
