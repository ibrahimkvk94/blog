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
    # Aynı anda kaç derslik gerektiği (birleşik derslerde 2 gibi) ve kilitli kartın tüm derslikleri.
    rooms_needed: int = 1
    fixed_rooms: tuple = ()
    # Yalnızca müsaitlik yüzünden kapalı başlangıçlar → kapatan varlıklar; "neden çözülemiyor"
    # açıklamasında müsaitlik kuralları tek tek gevşetilebilsin diye tutulur.
    blocked: dict = field(default_factory=dict)
    # Seçmeli dersler: aynı ders kümesini alan öğrenci topluluklarının anahtarları (aynı anda tek ders).
    students: tuple = ()
    subject: int | None = None

    def cells(self, day, period):
        return [(day, period + i) for i in range(self.length)]


@dataclass
class TeacherLimits:
    max_periods_per_day: int | None = None
    max_gaps_per_day: int | None = None
    max_gaps_per_week: int | None = None
    max_days_per_week: int | None = None
    max_consecutive: int | None = None
    min_periods_per_day: int | None = None  # yalnızca geldiği günlerde


@dataclass
class RelationshipSpec:
    """Kart ilişkisinin çözücüye hazır hali.

    groups: kuralın ayrı ayrı uygulandığı kart kümeleri (eşleşmeli koşullarda her ders bir küme).
    groups_b: iki taraflı koşullarda her kümenin B tarafı (groups ile aynı sırada).
    cells / cells_b: zaman haritası (None = tüm hücreler).
    rooms: derslik koşullarında seçili derslikler.
    weight: None ise sert kısıt, değilse ihlal başına ceza.
    """

    name: str
    condition: str
    param: int
    groups: list[list[int]]
    weight: int | None = None
    cells: frozenset | None = None
    id: int | None = None
    groups_b: list[list[int]] = field(default_factory=list)
    cells_b: frozenset | None = None
    rooms: tuple = ()


@dataclass
class TeacherPool:
    """Öğretmen havuzu: lessons'ın her birine quotas'taki öğretmenlerden biri atanır; her öğretmen tam
    quotas[t] ders alır. Havuzdaki derslerin kartlarında teachers boştur; seçilen öğretmenin müsaitliği
    (closed), çakışmaları ve kuralları çözücüde seçime bağlı uygulanır. hints: dersin şu anki öğretmeni."""

    name: str
    lessons: tuple[int, ...]
    quotas: dict[int, int]
    closed: dict[int, frozenset] = field(default_factory=dict)
    hints: dict[int, int] = field(default_factory=dict)


@dataclass
class Problem:
    days: int
    periods: int
    universes: frozenset[Universe]
    cards: list[ProblemCard]
    teacher_limits: dict[int, TeacherLimits] = field(default_factory=dict)
    lesson_max_per_day: dict[int, int] = field(default_factory=dict)
    room_blocked: dict[int, frozenset[Slot]] = field(default_factory=dict)
    room_slots: dict[int, int] = field(default_factory=dict)  # derslik → aynı anda en fazla ders (yoksa 1)
    teacher_available: dict[int, int] = field(default_factory=dict)
    atom_available: dict[str, int] = field(default_factory=dict)
    relationships: list[RelationshipSpec] = field(default_factory=list)
    class_limits: dict[int, tuple] = field(default_factory=dict)  # sınıf → (günde en az, günde en fazla)
    room_building: dict[int, int] = field(default_factory=dict)
    # Kurulum sırasında saptanan sorunlar: (düzey, kod, mesaj) — veri denetimi raporlar.
    notes: list = field(default_factory=list)
    labels: dict[str, dict] = field(default_factory=dict)
    # En az değişiklikle onarım (çözüm merkezi): kartın mevcut başlangıcı; oradan ayrılan her kart
    # anchor_weight ceza ekler. max_moves en fazla kaç kartın yer değiştirebileceği; forbidden_move_sets
    # daha önce önerilmiş "yer değiştiren kart kümeleri" (aynı öneri tekrar gelmesin).
    anchors: dict = field(default_factory=dict)
    anchor_weight: int = 200
    room_anchors: dict = field(default_factory=dict)  # kart → mevcut derslikleri (gereksiz derslik değişimi cezalı)
    max_moves: int | None = None
    forbidden_move_sets: list = field(default_factory=list)
    # Programı iyileştirme: öğretmen → (boşluk saati başına, okula gelinen gün başına) ceza.
    # Verilen öğretmenlerde varsayılan boşluk cezasının yerine geçer; gün cezası yalnızca burada vardır.
    teacher_weights: dict = field(default_factory=dict)
    teacher_pools: list[TeacherPool] = field(default_factory=list)

    def pooled_lessons(self):
        """{ders: havuz} — öğretmeni çözücünün seçeceği dersler."""
        return {lesson_id: pool for pool in self.teacher_pools for lesson_id in pool.lessons}

    @staticmethod
    def atom_class(atom_id):
        """Atom adı "sınıf|gruplar" biçimindedir; sınıf kısmı sayıysa int döner."""
        head = str(atom_id).split("|")[0]
        return int(head) if head.isdigit() else head

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
