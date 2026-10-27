"""Çözücünün Django'dan bağımsız problem tanımı.

Veritabanı modelleri builder.py'de bu sade yapılara çevrilir; böylece çözücü, denetimler ve
doğrulama saf Python olarak test edilebilir.

Zaman ızgarası (gün, saat) çiftlerinden oluşur. Haftalar ve dönemler "evren" (universe) olarak
modellenir: (hafta, dönem) çifti. İki kart ancak en az bir ortak evrende aktiflerse çakışabilir.
"""

import itertools
from dataclasses import dataclass, field

Slot = tuple[int, int]  # (gün, saat)
Universe = tuple[int, int]  # (hafta, dönem)


@dataclass
class ProblemCard:
    key: int
    lesson_id: int
    length: int
    teachers: tuple[int, ...]
    atoms: tuple[str, ...]
    room_options: tuple[int, ...]
    universes: frozenset[Universe]
    starts: list[Slot]
    maybe_slots: frozenset[Slot] = frozenset()
    fixed: Slot | None = None
    fixed_room: int | None = None
    hint: tuple[int, int, int | None] | None = None
    card_id: int | None = None

    def cells(self, day, period):
        return [(day, period + i) for i in range(self.length)]


@dataclass
class TeacherLimits:
    max_periods_per_day: int | None = None
    max_gaps_per_day: int | None = None
    max_gaps_per_week: int | None = None


@dataclass
class Problem:
    days: int
    periods: int
    universes: frozenset[Universe]
    cards: list[ProblemCard]
    teacher_limits: dict[int, TeacherLimits] = field(default_factory=dict)
    lesson_max_per_day: dict[int, int] = field(default_factory=dict)
    room_blocked: dict[int, frozenset[Slot]] = field(default_factory=dict)
    teacher_available: dict[int, int] = field(default_factory=dict)
    atom_available: dict[str, int] = field(default_factory=dict)
    labels: dict[str, dict] = field(default_factory=dict)

    def label(self, kind, key):
        return self.labels.get(kind, {}).get(key, f"{kind}#{key}")

    def cards_by(self, attr):
        """Kaynak → o kaynağı kullanan kart anahtarları (attr: 'teachers', 'atoms', 'room_options')."""
        index = {}
        for card in self.cards:
            for res in getattr(card, attr):
                index.setdefault(res, []).append(card.key)
        return index


def class_atoms(class_id, divisions):
    """Sınıfın atomik öğrenci kümeleri: bölünmelerin gruplarının kartezyen çarpımı.

    divisions: her bölünme için grup kimliklerinin listesi. Dönüş: {atom_id: grup_kimlikleri}.
    """
    non_empty = [groups for groups in divisions if groups]
    atoms = {}
    for combo in itertools.product(*non_empty):
        atom_id = f"{class_id}|" + "-".join(str(g) for g in combo)
        atoms[atom_id] = frozenset(combo)
    return atoms


def lesson_atoms(lesson_classes, lesson_groups, atoms_by_class, class_of_group):
    """Bir dersin etkilediği atomlar. Grubu seçilmemiş sınıflarda tüm sınıf etkilenir."""
    groups_by_class = {}
    for group_id in lesson_groups:
        groups_by_class.setdefault(class_of_group[group_id], set()).add(group_id)
    result = []
    for class_id in lesson_classes:
        atoms = atoms_by_class[class_id]
        chosen = groups_by_class.get(class_id)
        for atom_id, groups in atoms.items():
            if not chosen or groups & chosen:
                result.append(atom_id)
    return tuple(result)


def mask_bits(mask, count):
    """Bit maskesini indeks kümesine çevirir; None 'hepsi' demektir."""
    if mask is None:
        return set(range(count))
    return {i for i in range(count) if mask >> i & 1}


def card_universes(weeks_mask, terms_mask, weeks_count, terms_count):
    weeks = mask_bits(weeks_mask, weeks_count)
    terms = mask_bits(terms_mask, terms_count)
    return frozenset(itertools.product(weeks, terms))
