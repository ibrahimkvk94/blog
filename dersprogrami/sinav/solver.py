"""Sınav programı çözücüsü (OR-Tools CP-SAT). Veritabanından bağımsızdır: Problem alır, Result döndürür.

Zaman dilimi (slot) = gün sırası × oturum sayısı + oturum. Çözüm üç aşamada bulunur:

1. Zamanlama: her sınava bir başlangıç oturumu. Kesin kurallar: bir sınıfın (ya da ortak öğrencisi olan iki
   sınavın) aynı oturumda iki sınavı olmaz; sınıfın günde en fazla N sınavı; sabit / kilitli sınavlar yerinde;
   her oturumda sınavların toplam öğrencisi salonların toplam sınav kapasitesini, gereken salon sayısı salon
   sayısını, gereken gözetmen sayısı o oturumda müsait öğretmen sayısını aşmaz. Yerleşemeyen sınav büyük
   cezayla boş bırakılabilir (sonuç "kısmen"). Tercihler: sınıfın sınavları günlere yayılsın, aynı gün art arda
   oturumlara düşmesin, aynı öğretmenin iki sınavı aynı anda olmasın.
2. Salonlar: her sınava toplam sınav kapasitesi öğrenci sayısına yeten salonlar (bir sınav birden çok salona
   bölünebilir); bir salonda aynı anda tek sınav. Tercih: az salon, öğrenci sayısına yakın kapasite.
3. Gözetmenler: her salona gereken sayıda öğretmen; öğretmen aynı anda iki salonda olamaz, müsait olmadığı
   oturumda görev almaz. Tercihler: dersin kendi öğretmeni sınavında bulunsun, yük öğretmenlere dengeli dağılsın
   (en yüksek yük ve ortalamanın üstü cezalı, günde ikiden fazla görev cezalı).
   KAMYOSİS: görev rolleri açıksa salon başına salon amiri / gözetmen / taşıyıcı ihtiyacı öğrenci sayısından
   hesaplanır (duty_need) ve öğretmen yalnızca alabileceği rolde görevlendirilir; "mümkünse verilmesin" oturumu
   cezalıdır; yük, öğretmenin önceki görev puanı (prior) üstüne eklenerek dengelenir; hafta sonu görevi 1,5 sayılır.

Her aşamada açgözlü bir başlangıç çözümü ipucu olarak verilir; CP-SAT süre içinde çözüm bulamazsa o kullanılır.

KAMYOSİS tercihleri (zamanlama aşaması, bkz. kurallar.py): zorluğu yüksek sınav erken güne (eşit zorlukta MT önce,
ÇS sonra), adı aynı (parantez hariç) sınavlar aynı güne, bir oturuma tek sınıf düzeyi (1. / 2. sınıf). Oturum düzeni
verilmişse (ör. 2,1,2,1) her oturum o düzeyin sınavlarına ayrılır; o oturumda düzeyin her bölümü (programı) tam bir
sınavda olsun: aynı bölümün iki sınavı (mükerrer) ve sınavı olmayan bölüm (eksik) cezalıdır.
"""

import math
import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

W_UNPLACED = 100000
W_SPREAD = 40
W_SAME_DAY = 6
W_ADJACENT = 4
W_TEACHER_CLASH = 25
W_UNROOMED = 100000
W_ROOM = 30
W_SHORT = 100000
W_OWN = 40
W_MAX_LOAD = 30
W_OVER = 12
W_DAY_OVER = 8
DAY_LOAD_FREE = 2
W_SOFT = 60            # KAMYOSİS: "mümkünse görev verilmesin" oturumunda görev
ROLE_LABELS = {"A": "salon amiri", "G": "gözetmen", "T": "taşıyıcı"}
# KAMYOSİS tercihleri
W_ORDER = 1            # (3 × zorluk + tür sırası) × gün sırası
W_SAME_NAME_DAY = 300  # adı aynı sınavların kullandığı her fazladan gün
W_MIXED_YEAR = 60      # bir oturumda birden çok sınıf düzeyi
TYPE_RANK = {"MT": 2, "": 1, "ÇS": 0}
W_PATTERN = 5000       # sınav, oturum düzenindeki düzeyin dışındaki oturumda
W_DUP_PROGRAM = 3000   # aynı oturumda aynı bölümün ikinci sınavı
W_MISSING_PROGRAM = 150  # düzeyin oturumunda sınavı olmayan bölüm


@dataclass
class PExam:
    id: int
    name: str
    classes: tuple = ()
    students: int = 0
    duration: int = 1
    teachers: tuple = ()
    fixed: int | None = None          # sabit başlangıç dilimi
    rooms_needed: int | None = None
    allowed_rooms: tuple = ()         # boş = tümü
    locked_rooms: tuple = ()          # kilitli yerleşimin salonları (değişmez)
    locked_proctors: dict = field(default_factory=dict)  # {salon: ((öğretmen, rol), ...)}
    student_ids: frozenset = frozenset()
    # KAMYOSİS: zorluk (1–5), tür ailesi ("MT", "ÇS", ""), sınıf düzeyi (1, 2 …; None = bilinmiyor),
    # parantez içi hariç ad (aynı ad aynı güne)
    difficulty: int = 3
    family: str = ""
    year: int | None = None
    base_name: str = ""
    programs: frozenset = frozenset()  # KAMYOSİS: sınavın bölümleri (kısımların programı)

    @property
    def priority(self):
        """Erken yerleşme önceliği: zorluk, eşitse tür (MT > diğer > ÇS)."""
        return 3 * self.difficulty + TYPE_RANK.get(self.family, 1)


@dataclass
class PRoom:
    id: int
    name: str
    capacity: int                     # sınav kapasitesi


@dataclass
class Problem:
    n_days: int
    n_sessions: int
    exams: list
    rooms: list
    proctors: list                    # öğretmen kimlikleri
    unavailable: dict = field(default_factory=dict)  # {öğretmen: {dilim, ...}}
    max_per_day: int = 2
    proctors_per_room: int = 1
    time_limit: float = 30
    class_names: dict = field(default_factory=dict)
    slot_names: list = field(default_factory=list)   # dilim → "03.11.2026 Salı 09:30"
    capacity_percent: int = 50
    workers: int = 8
    # KAMYOSİS görev kuralları
    duty_roles: bool = False                         # salon amiri / gözetmen / taşıyıcı
    roles: dict = field(default_factory=dict)        # {öğretmen: "AGT"}; kayıt yok = "G"
    soft: dict = field(default_factory=dict)         # {öğretmen: {dilim, ...}} mümkünse görev verilmesin
    prior: dict = field(default_factory=dict)        # {öğretmen: önceki görev puanı × 2}
    weekend: frozenset = frozenset()                 # hafta sonu dilimleri (görev 1,5 sayılır)
    session_years: tuple = ()                        # oturum sırası → sınıf düzeyi (ör. (2, 1, 2, 1)); boş = serbest
    carriers_per_session: int = 0                    # rollü dönemde oturum başına taşıyıcı (0 = salon başına 1)
    programs_by_year: dict = field(default_factory=dict)  # {düzey: {bölüm, ...}}

    def slot_year(self, t):
        """Oturum düzenine göre bu dilimin sınıf düzeyi (yoksa None)."""
        s = t % self.n_sessions if self.n_sessions else 0
        return self.session_years[s] if s < len(self.session_years) else None

    @property
    def n_slots(self):
        return self.n_days * self.n_sessions


@dataclass
class Result:
    status: str                       # ok / partial / failed
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # {sınav: (başlangıç dilimi, [(salon, oturan, [öğretmen, ...], {öğretmen: rol}), ...])}
    placements: dict = field(default_factory=dict)
    unplaced: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _starts(p, exam):
    if exam.fixed is not None:
        return [exam.fixed]
    s, d = p.n_sessions, max(1, exam.duration)
    return [day * s + k for day in range(p.n_days) for k in range(s - d + 1)]


def _candidate_rooms(p, exam):
    allowed = set(exam.allowed_rooms)
    if exam.locked_rooms:
        allowed = set(exam.locked_rooms)
    return [r for r in p.rooms if not allowed or r.id in allowed]


def _min_rooms(p, exam):
    caps = sorted((r.capacity for r in _candidate_rooms(p, exam)), reverse=True)
    total, k = 0, 0
    for c in caps:
        if total >= exam.students and k >= 1:
            break
        total += c
        k += 1
    k = max(k, 1)
    if exam.rooms_needed:
        k = max(k, exam.rooms_needed)
    if exam.locked_rooms:
        k = len(exam.locked_rooms)
    return k


def _available(p, teacher, slots):
    blocked = p.unavailable.get(teacher) or ()
    return not any(t in blocked for t in slots)


def duty_need(p, seats):
    """Salonun görevli ihtiyacı {rol: sayı}. Rolsüz: salon başına sabit gözetmen. Rollü (PPYS kuralı): 40 ve üstü
    öğrencide 1 salon amiri; 40'tan azda 1, fazlasında her 20 öğrenciye 1 gözetmen; öğrencisi olan salona 1 taşıyıcı.
    KAMYOSİS: carriers_per_session verilmişse taşıyıcı salona değil oturuma atanır (bkz. _needs)."""
    if not p.duty_roles:
        return {"G": p.proctors_per_room} if p.proctors_per_room else {}
    need = {"A": int(seats >= 40), "G": 1 if seats < 40 else -(-seats // 20),
            "T": int(seats > 0) if not p.carriers_per_session else 0}
    return {r: n for r, n in need.items() if n}


def _duty_pool(p):
    return [t for t in p.proctors if p.roles.get(t, "G")]


def _duties_on(p):
    return p.duty_roles or bool(p.proctors_per_room)


def _duty_estimate(p, e, k):
    """Zamanlama aşaması için sınavın görevli sayısı tahmini (k salona eşit bölünmüş öğrenciyle)."""
    if not k or not _duties_on(p):
        return 0
    per = -(-e.students // k) if e.students else 0
    return k * sum(duty_need(p, per).values())


def _weight(p, slots):
    """Görev puanı × 2: hafta içi oturum 2, hafta sonu 3."""
    return sum(3 if s in p.weekend else 2 for s in slots)


def _is_soft(p, teacher, slots):
    soft = p.soft.get(teacher) or ()
    return any(t in soft for t in slots)


def _water_level(priors, total):
    """Önceki puanların üstüne toplam yük dağıtılınca ulaşılacak eşit düzey (en küçük L: Σ max(0, L − önceki) ≥ toplam)."""
    if not priors:
        return 0
    lo, hi = 0, max(priors) + total + 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sum(max(0, mid - x) for x in priors) >= total:
            hi = mid
        else:
            lo = mid + 1
    return lo


def _slot_label(p, t):
    if 0 <= t < len(p.slot_names):
        return p.slot_names[t]
    return f"{t // p.n_sessions + 1}. gün {t % p.n_sessions + 1}. oturum"


# --- ön denetim ---------------------------------------------------------------------------------

def precheck(p):
    """Çözümü baştan imkânsız kılan durumlar: açık, kullanıcıya dönük iletiler."""
    errors = []
    if p.n_slots == 0:
        return ["Sınav döneminde uygun gün ya da oturum yok: tarih aralığını, sınav günlerini ve oturum saatlerini denetleyin."]
    if not p.rooms:
        return ["Sınav salonu yok: dersliklerin kapasitesini girin ya da dönem ayarlarında “kapasitesiz derslikte sınav "
                "kapasitesi” verin."]
    if _duties_on(p) and not _duty_pool(p):
        errors.append("Gözetmen olabilecek öğretmen yok (hepsi muaf ya da görev rolü yok).")
    for e in p.exams:
        if e.duration > p.n_sessions:
            errors.append(f"«{e.name}»: süresi {e.duration} oturum, günde yalnızca {p.n_sessions} oturum var.")
        if e.fixed is not None and not 0 <= e.fixed < p.n_slots:
            errors.append(f"«{e.name}»: sabit tarih/oturum sınav dönemi içinde değil (hariç gün ya da dönem dışı).")
        elif e.fixed is not None and e.fixed % p.n_sessions + e.duration > p.n_sessions:
            errors.append(f"«{e.name}»: sabit oturumdan başlayınca {e.duration} oturumluk süre günün sonuna sığmıyor.")
        rooms = _candidate_rooms(p, e)
        cap = sum(r.capacity for r in rooms)
        if not rooms:
            errors.append(f"«{e.name}»: seçilen salonların hiçbiri sınav salonu değil.")
        elif e.students > cap:
            errors.append(
                f"«{e.name}» için salon kapasitesi yetersiz: {e.students} öğrenci, kullanılabilir salonların toplam sınav "
                f"kapasitesi {cap} (derslik kapasitesinin %{p.capacity_percent}'i). Salon ekleyin, sınav kapasitesi oranını "
                "artırın ya da sınavı bölün.")
        elif e.rooms_needed and e.rooms_needed > len(rooms):
            errors.append(f"«{e.name}»: {e.rooms_needed} salon isteniyor, kullanılabilir {len(rooms)} salon var.")
    by_class = {}
    for e in p.exams:
        for c in e.classes:
            by_class.setdefault(c, []).append(e)
    for c, exams in sorted(by_class.items(), key=lambda kv: str(p.class_names.get(kv[0], kv[0]))):
        name = p.class_names.get(c, c)
        sessions = sum(e.duration for e in exams)
        if sessions > p.n_slots:
            errors.append(f"{name} sınıfının {len(exams)} sınavı {sessions} oturum tutuyor; dönemde yalnızca {p.n_slots} oturum var.")
        elif len(exams) > p.max_per_day * p.n_days:
            errors.append(
                f"{name} sınıfının {len(exams)} sınavı var; günde en fazla {p.max_per_day} sınavla {p.n_days} günde en çok "
                f"{p.max_per_day * p.n_days} sınav yapılabilir. Günlük sınırı artırın ya da günleri çoğaltın.")
    # sabit sınavların çakışması
    fixed_at = {}
    for e in p.exams:
        if e.fixed is None or not 0 <= e.fixed < p.n_slots:
            continue
        for k in range(e.duration):
            for c in e.classes:
                other = fixed_at.get((c, e.fixed + k))
                if other is not None and other is not e:
                    errors.append(f"Sabit sınavlar çakışıyor: «{other.name}» ve «{e.name}» ({p.class_names.get(c, c)}, "
                                  f"{_slot_label(p, e.fixed + k)}).")
                fixed_at[(c, e.fixed + k)] = e
    return list(dict.fromkeys(errors))


# --- 1. zamanlama -------------------------------------------------------------------------------

def _greedy_timing(p, need):
    """Başlangıç çözümü: büyük ve çok sınıflı sınavlar önce, kuralları bozmayan ilk (en az dolu) oturuma."""
    S, T = p.n_sessions, p.n_slots
    total_cap = sum(r.capacity for r in p.rooms)
    pool = _duty_pool(p)
    free = [sum(1 for tch in pool if t not in (p.unavailable.get(tch) or ())) for t in range(T)]
    seats, rooms, proctors = [0] * T, [0] * T, [0] * T
    class_busy, class_day = set(), {}
    out = {}
    order = sorted(range(len(p.exams)), key=lambda i: (p.exams[i].fixed is None, -p.exams[i].priority, -need[p.exams[i].id],
                                                       -len(p.exams[i].classes), -p.exams[i].students))
    for i in order:
        e = p.exams[i]
        k = need[e.id]
        best = None
        for t in _starts(p, e):
            span = range(t, t + e.duration)
            if any((c, s) in class_busy for c in e.classes for s in span):
                continue
            if any(class_day.get((c, t // S), 0) >= p.max_per_day for c in e.classes):
                continue
            if any(seats[s] + e.students > total_cap or rooms[s] + k > len(p.rooms) for s in span):
                continue
            duty = _duty_estimate(p, e, k)
            if duty and any(proctors[s] + duty > free[s] for s in span):
                continue
            load = max(rooms[s] for s in span) + sum(class_day.get((c, t // S), 0) for c in e.classes) * 2
            load += (t // S) * e.priority / 3  # KAMYOSİS: zor sınav erken güne
            if e.year is not None and p.slot_year(t) not in (None, e.year):
                load += 1000  # KAMYOSİS: oturum düzeni
            if best is None or load < best[0]:
                best = (load, t)
        if best is None:
            continue
        t = best[1]
        out[i] = t
        for s in range(t, t + e.duration):
            seats[s] += e.students
            rooms[s] += k
            proctors[s] += _duty_estimate(p, e, k)
            for c in e.classes:
                class_busy.add((c, s))
        for c in e.classes:
            class_day[(c, t // S)] = class_day.get((c, t // S), 0) + 1
    return out


def _solve_timing(p, limit):
    m = cp_model.CpModel()
    S, T = p.n_sessions, p.n_slots
    total_cap = sum(r.capacity for r in p.rooms)
    n_rooms = len(p.rooms)
    need = {e.id: _min_rooms(p, e) for e in p.exams}
    x, unplaced, cover, day_start = {}, {}, [[] for _ in range(T)], {}
    obj = []
    for i, e in enumerate(p.exams):
        starts = _starts(p, e)
        for t in starts:
            x[i, t] = m.NewBoolVar(f"x{i}_{t}")
            for k in range(e.duration):
                cover[t + k].append((i, x[i, t]))
            day_start.setdefault((i, t // S), []).append(x[i, t])
        if e.fixed is not None:
            m.Add(sum(x[i, t] for t in starts) == 1)
        else:
            unplaced[i] = m.NewBoolVar(f"u{i}")
            m.Add(sum(x[i, t] for t in starts) + unplaced[i] == 1)
            obj.append(W_UNPLACED * unplaced[i])
    greedy = _greedy_timing(p, need)
    for (i, t), v in x.items():
        m.AddHint(v, int(greedy.get(i) == t))
    for i, v in unplaced.items():
        m.AddHint(v, int(i not in greedy))

    by_class = {}
    for i, e in enumerate(p.exams):
        for c in e.classes:
            by_class.setdefault(c, []).append(i)
    cover_by = [dict() for _ in range(T)]
    for t in range(T):
        for i, v in cover[t]:
            cover_by[t].setdefault(i, []).append(v)

    def occ(i, t):
        return cover_by[t].get(i, [])

    # sınıf çakışması ve günlük sınır
    for c, ids in by_class.items():
        for t in range(T):
            terms = [v for i in ids for v in occ(i, t)]
            if len(terms) > 1:
                m.Add(sum(terms) <= 1)
        if len(ids) > 1:
            target = math.ceil(len(ids) / max(1, p.n_days))
            for d in range(p.n_days):
                terms = [v for i in ids for v in day_start.get((i, d), [])]
                if len(terms) > p.max_per_day:
                    m.Add(sum(terms) <= p.max_per_day)
                if len(terms) > 1:
                    same = m.NewIntVar(0, len(terms), f"sd{c}_{d}")
                    m.Add(same >= sum(terms) - 1)
                    obj.append(W_SAME_DAY * same)
                if len(terms) > target:
                    over = m.NewIntVar(0, len(terms), f"sp{c}_{d}")
                    m.Add(over >= sum(terms) - target)
                    obj.append(W_SPREAD * over)
                for s in range(S - 1):
                    a = [v for i in ids for v in occ(i, d * S + s)]
                    b = [v for i in ids for v in occ(i, d * S + s + 1)]
                    if a and b:
                        adj = m.NewBoolVar(f"adj{c}_{d}_{s}")
                        m.Add(adj >= sum(a) + sum(b) - 1)
                        obj.append(W_ADJACENT * adj)

    # ortak öğrencisi olan, ortak sınıfı olmayan sınavlar
    for i, a in enumerate(p.exams):
        if not a.student_ids:
            continue
        for j in range(i + 1, len(p.exams)):
            b = p.exams[j]
            if b.student_ids and not set(a.classes) & set(b.classes) and a.student_ids & b.student_ids:
                for t in range(T):
                    terms = occ(i, t) + occ(j, t)
                    if len(terms) > 1:
                        m.Add(sum(terms) <= 1)

    # oturum başına kapasite, salon ve gözetmen sayısı
    for t in range(T):
        if not cover[t]:
            continue
        m.Add(sum(v * p.exams[i].students for i, v in cover[t]) <= total_cap)
        m.Add(sum(v * need[p.exams[i].id] for i, v in cover[t]) <= n_rooms)
        if _duties_on(p):
            free = sum(1 for tch in _duty_pool(p) if t not in (p.unavailable.get(tch) or ()))
            m.Add(sum(v * _duty_estimate(p, p.exams[i], need[p.exams[i].id]) for i, v in cover[t]) <= free)

    # aynı öğretmenin iki sınavı aynı anda olmasın (tercih)
    by_teacher = {}
    for i, e in enumerate(p.exams):
        for tch in e.teachers:
            by_teacher.setdefault(tch, []).append(i)
    for tch, ids in by_teacher.items():
        if len(ids) < 2:
            continue
        for t in range(T):
            terms = [v for i in ids for v in occ(i, t)]
            if len(terms) > 1:
                clash = m.NewIntVar(0, len(terms), f"tc{tch}_{t}")
                m.Add(clash >= sum(terms) - 1)
                obj.append(W_TEACHER_CLASH * clash)

    obj += _kamyosis_terms(m, p, x, occ, day_start)

    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, limit)
    solver.parameters.num_workers = p.workers
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, status
    timing = {}
    for (i, t), v in x.items():
        if solver.Value(v):
            timing[p.exams[i].id] = t
    return timing, status


def _kamyosis_terms(m, p, x, occ, day_start):
    """KAMYOSİS tercihleri: zorluk/tür sırası, aynı ad aynı gün, oturumda tek sınıf düzeyi. Amaç terimleri döner."""
    S, T = p.n_sessions, p.n_slots
    obj = []
    # zor sınav (eşitse MT) erken güne: başlangıç gününün sırası × öncelik
    for (i, t), v in x.items():
        if t // S:
            obj.append(W_ORDER * p.exams[i].priority * (t // S) * v)
    # adı aynı sınavlar aynı güne: grubun kullandığı gün sayısı − 1
    by_name = {}
    for i, e in enumerate(p.exams):
        if e.base_name:
            by_name.setdefault(e.base_name, []).append(i)
    for n, ids in enumerate(by_name.values()):
        if len(ids) < 2:
            continue
        used = []
        for d in range(p.n_days):
            starts = [v for i in ids for v in day_start.get((i, d), [])]
            if starts:
                u = m.NewBoolVar(f"nd{n}_{d}")
                for v in starts:
                    m.AddImplication(v, u)
                used.append(u)
        if len(used) > 1:
            extra = m.NewIntVar(0, len(used), f"ne{n}")
            m.Add(extra >= sum(used) - 1)
            obj.append(W_SAME_NAME_DAY * extra)
    # oturum düzeni: sınav kendi düzeyinin oturumunda
    if p.session_years:
        for (i, t), v in x.items():
            want = p.slot_year(t)
            if want is not None and p.exams[i].year not in (None, want):
                obj.append(W_PATTERN * v)
    # bölümler: oturumda aynı bölümün tek sınavı (mükerrer yok), düzeyin oturumunda her bölüm (eksik yok)
    by_program = {}
    for i, e in enumerate(p.exams):
        for pr in e.programs:
            by_program.setdefault(pr, []).append(i)
    for pr, ids in by_program.items():
        year = next((y for y, prs in p.programs_by_year.items() if pr in prs), None)
        for t in range(T):
            terms = [v for i in ids for v in occ(i, t)]
            if len(terms) > 1:
                dup = m.NewIntVar(0, len(terms), f"pd{t}_{len(obj)}")
                m.Add(dup >= sum(terms) - 1)
                obj.append(W_DUP_PROGRAM * dup)
            if p.session_years and year is not None and p.slot_year(t) == year:
                if terms:
                    here = m.NewBoolVar(f"ph{t}_{len(obj)}")
                    m.Add(here <= sum(terms))
                    obj.append(W_MISSING_PROGRAM * (1 - here))
    # oturumda tek sınıf düzeyi: oturumdaki düzey sayısı − 1
    years = sorted({e.year for e in p.exams if e.year is not None})
    if len(years) > 1:
        for t in range(T):
            present = []
            for y in years:
                terms = [v for i, e in enumerate(p.exams) if e.year == y for v in occ(i, t)]
                if terms:
                    h = m.NewBoolVar(f"yr{t}_{y}")
                    for v in terms:
                        m.AddImplication(v, h)
                    present.append(h)
            if len(present) > 1:
                mixed = m.NewIntVar(0, len(present), f"ym{t}")
                m.Add(mixed >= sum(present) - 1)
                obj.append(W_MIXED_YEAR * mixed)
    return obj


# --- 2. salonlar --------------------------------------------------------------------------------

def _greedy_rooms(p, timing):
    by_id = {e.id: e for e in p.exams}
    busy = {}  # (salon, dilim) → sınav
    out = {}
    for eid in sorted(timing, key=lambda k: (-len(by_id[k].locked_rooms), -by_id[k].students)):
        e = by_id[eid]
        slots = range(timing[eid], timing[eid] + e.duration)
        free = [r for r in _candidate_rooms(p, e) if all((r.id, t) not in busy for t in slots)]
        if e.locked_rooms:
            chosen = [r for r in free if r.id in e.locked_rooms]
        else:
            chosen, total = [], 0
            want = e.rooms_needed or 0
            # önce tek salonda sığdır, sığmazsa büyükten küçüğe doldur
            single = sorted((r for r in free if r.capacity >= e.students), key=lambda r: r.capacity)
            if single and want <= 1:
                chosen = [single[0]]
            else:
                for r in sorted(free, key=lambda r: -r.capacity):
                    if (total >= e.students and len(chosen) >= max(1, want)) or (want and len(chosen) >= want):
                        break
                    chosen.append(r)
                    total += r.capacity
        if sum(r.capacity for r in chosen) < e.students or not chosen:
            continue
        for r in chosen:
            for t in slots:
                busy[r.id, t] = eid
        out[eid] = [r.id for r in chosen]
    return out


def _solve_rooms(p, timing, limit):
    by_id = {e.id: e for e in p.exams}
    caps = {r.id: r.capacity for r in p.rooms}
    greedy = _greedy_rooms(p, timing)
    m = cp_model.CpModel()
    y, ok, obj = {}, {}, []
    active = {}
    for eid, t0 in timing.items():
        e = by_id[eid]
        ok[eid] = m.NewBoolVar(f"ok{eid}")
        obj.append(W_UNROOMED * (1 - ok[eid]))
        rooms = _candidate_rooms(p, e)
        for r in rooms:
            y[eid, r.id] = m.NewBoolVar(f"y{eid}_{r.id}")
            m.Add(y[eid, r.id] <= ok[eid])
            m.AddHint(y[eid, r.id], int(r.id in greedy.get(eid, ())))
            obj.append((W_ROOM + r.capacity) * y[eid, r.id])
            for t in range(t0, t0 + e.duration):
                active.setdefault((r.id, t), []).append(y[eid, r.id])
        m.AddHint(ok[eid], int(eid in greedy))
        terms = [y[eid, r.id] for r in rooms]
        if e.locked_rooms:
            for r in rooms:
                m.Add(y[eid, r.id] == ok[eid])
        if e.students:
            m.Add(sum(y[eid, r.id] * r.capacity for r in rooms) >= e.students * ok[eid])
        if e.rooms_needed and not e.locked_rooms:
            m.Add(sum(terms) == e.rooms_needed * ok[eid])
        else:
            m.Add(sum(terms) >= ok[eid])
    for terms in active.values():
        if len(terms) > 1:
            m.Add(sum(terms) <= 1)
    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, limit)
    solver.parameters.num_workers = p.workers
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return greedy
    out = {}
    for eid in timing:
        if solver.Value(ok[eid]):
            out[eid] = sorted((rid for (e2, rid), v in y.items() if e2 == eid and solver.Value(v)),
                              key=lambda rid: -caps[rid])
    return out


def seat_split(students, capacities):
    """Öğrencileri salonlara dağıtır (kapasite oranında, toplam = öğrenci). capacities sıralı liste."""
    total = sum(capacities)
    if not capacities:
        return []
    if total <= 0:
        return [0] * len(capacities)
    seats = [min(c, students * c // total) for c in capacities]
    rest = students - sum(seats)
    i = 0
    while rest > 0 and i < 10 * len(capacities):
        k = i % len(capacities)
        if seats[k] < capacities[k]:
            seats[k] += 1
            rest -= 1
        i += 1
    seats[0] += max(0, rest)
    return seats


# --- 3. gözetmenler -----------------------------------------------------------------------------

def _units(p, timing, rooms):
    by_id = {e.id: e for e in p.exams}
    units = []
    for eid, rids in rooms.items():
        e = by_id[eid]
        slots = tuple(range(timing[eid], timing[eid] + e.duration))
        for rid in rids:
            units.append((eid, rid, slots))
    return units


def _locked(p, e, rid):
    """Kilitli yerleşimdeki salonun görevlileri [(öğretmen, rol)] (problemdeki öğretmenler)."""
    known = set(p.proctors)
    return [(t, r) for t, r in e.locked_proctors.get(rid, ()) if t in known]


def _unit_need(p, e, rid, seats):
    locked = _locked(p, e, rid)
    if locked:
        need = {}
        for _t, r in locked:
            need[r] = need.get(r, 0) + 1
        return need, locked
    return duty_need(p, seats), []


def _needs(p, units, seats):
    """{(sınav, salon): (ihtiyaç, kilitli görevliler)}. Oturum başına taşıyıcı, oturumda başlayan kilitsiz sınavların en
    kalabalık salonuna yazılır (taşıyıcı salona değil oturuma aittir)."""
    by_id = {e.id: e for e in p.exams}
    out = {(eid, rid): _unit_need(p, by_id[eid], rid, seats.get((eid, rid), 0)) for eid, rid, _s in units}
    if p.duty_roles and p.carriers_per_session:
        reps = {}
        for eid, rid, slots in units:
            if out[eid, rid][1]:
                continue
            key = (-seats.get((eid, rid), 0), rid)
            if slots[0] not in reps or key < reps[slots[0]][0]:
                reps[slots[0]] = (key, (eid, rid))
        for _key, unit in reps.values():
            out[unit][0]["T"] = p.carriers_per_session
    return out


def _greedy_proctors(p, timing, rooms, seats):
    by_id = {e.id: e for e in p.exams}
    load = {t: p.prior.get(t, 0) for t in p.proctors}
    tasima = {t: 0 for t in p.proctors}  # taşıyıcı görevleri dengeye girmez; yalnızca sırayı yaymak için
    busy = set()
    out = {}
    units = _units(p, timing, rooms)
    needs = _needs(p, units, seats)
    for eid, rid, slots in sorted(units, key=lambda u: (u[2][0], -len(by_id[u[0]].locked_proctors))):
        e = by_id[eid]
        need, chosen = needs[eid, rid]
        chosen = list(chosen)
        if not chosen:
            own = set(e.teachers)
            taken = set()
            for role, n in need.items():
                pool = sorted((t for t in p.proctors if role in p.roles.get(t, "G")),
                              key=lambda t: (_is_soft(p, t, slots), t not in own,
                                             tasima[t] if role == "T" and p.carriers_per_session else load[t], t))
                for t in pool:
                    if n <= 0:
                        break
                    if t in taken or any((t, s) in busy for s in slots) or not _available(p, t, slots):
                        continue
                    chosen.append((t, role))
                    taken.add(t)
                    n -= 1
        for t, r in chosen:
            if r == "T" and p.carriers_per_session:
                tasima[t] += 1
            else:
                load[t] += _weight(p, slots)
            for s in slots:
                busy.add((t, s))
        out[eid, rid] = chosen
    return out


def _solve_proctors(p, timing, rooms, seats, limit):
    units = _units(p, timing, rooms)
    if not _duties_on(p) or not units:
        return {(eid, rid): [] for eid, rid, _ in units}
    by_id = {e.id: e for e in p.exams}
    greedy = _greedy_proctors(p, timing, rooms, seats)
    m = cp_model.CpModel()
    w, obj = {}, []
    per_slot = {}
    loads = {t: [] for t in p.proctors}
    day_loads = {}
    total = 0
    needs = _needs(p, units, seats)
    for u, (eid, rid, slots) in enumerate(units):
        e = by_id[eid]
        need, locked = needs[eid, rid]
        hint = set(greedy.get((eid, rid), ()))
        weight = _weight(p, slots)
        for role, n in need.items():
            # KAMYOSİS: oturum başına taşıyıcı görevi sınırsızdır: dengeye ve günlük yüke girmez
            serbest = role == "T" and bool(p.carriers_per_session)
            if not serbest:
                total += n * weight
            terms = []
            for tch in p.proctors:
                if locked:
                    if (tch, role) not in locked:
                        continue
                elif role not in p.roles.get(tch, "G") or not _available(p, tch, slots):
                    continue
                v = m.NewBoolVar(f"w{u}_{role}_{tch}")
                w[u, role, tch] = v
                m.AddHint(v, int((tch, role) in hint))
                if locked:
                    m.Add(v == 1)
                elif _is_soft(p, tch, slots):
                    obj.append(W_SOFT * v)
                terms.append(v)
                for s in slots:
                    per_slot.setdefault((tch, s), []).append(v)
                if serbest:
                    continue
                loads[tch].append(v * weight)
                day_loads.setdefault((tch, slots[0] // p.n_sessions), []).append(v * len(slots))
            short = m.NewIntVar(0, n, f"short{u}_{role}")
            m.Add(sum(terms) + short == n)
            obj.append(W_SHORT * short)
    for terms in per_slot.values():
        if len(terms) > 1:
            m.Add(sum(terms) <= 1)
    # dersin öğretmeni kendi sınavında
    for eid in rooms:
        e = by_id[eid]
        if not e.teachers:
            continue
        terms = [v for (u, _r, t), v in w.items() if units[u][0] == eid and t in e.teachers]
        if terms:
            own = m.NewBoolVar(f"own{eid}")
            m.Add(own <= sum(terms))
            obj.append(W_OWN * (1 - own))
    # denge: önceki puan + bu dönemin yükü eşit düzeye yaklaşsın (önceki puan yoksa ortalama)
    active = [t for t, terms in loads.items() if terms]
    level = _water_level([p.prior.get(t, 0) for t in active], total)
    top = total + max((p.prior.get(t, 0) for t in active), default=0)
    max_load = m.NewIntVar(0, top, "maxload")
    obj.append(W_MAX_LOAD * max_load)
    for tch in active:
        final = p.prior.get(tch, 0) + sum(loads[tch])
        m.Add(max_load >= final)
        over = m.NewIntVar(0, top, f"over{tch}")
        m.Add(over >= final - level)
        obj.append(W_OVER * over)
    for key, terms in day_loads.items():
        if len(terms) > 1:
            over = m.NewIntVar(0, total, f"dover{key[0]}_{key[1]}")
            m.Add(over >= sum(terms) - DAY_LOAD_FREE)
            obj.append(W_DAY_OVER * over)
    m.Minimize(sum(obj))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, limit)
    solver.parameters.num_workers = p.workers
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return greedy
    out = {(eid, rid): [] for eid, rid, _s in units}
    for (u, role, tch), v in w.items():
        if solver.Value(v):
            out[units[u][0], units[u][1]].append((tch, role))
    return out


# --- giriş noktası ------------------------------------------------------------------------------

def solve(p, progress=None):
    started = time.monotonic()
    errors = precheck(p)
    if errors:
        return Result("failed", errors=errors)
    if not p.exams:
        return Result("failed", errors=["Yerleştirilecek sınav yok: önce “Derslerden oluştur” ile sınavları ekleyin."])

    def remaining(share):
        return max(1.0, (p.time_limit - (time.monotonic() - started)) * share)

    if progress:
        progress("Sınav zamanları aranıyor…")
    timing, status = _solve_timing(p, p.time_limit * 0.55)
    if timing is None:
        if status == cp_model.INFEASIBLE:
            msg = ("Sabit ya da kilitli sınavlar kuralları ihlal ediyor (aynı oturumda salon/gözetmen yetmiyor ya da sınıfın "
                   "günlük sınırı aşılıyor). Sabit tarihleri ve kilitleri gözden geçirin.")
        else:
            msg = "Süre içinde çözüm bulunamadı; süre sınırını artırıp yeniden deneyin."
        return Result("failed", errors=[msg])
    if progress:
        progress("Salonlar atanıyor…")
    rooms = _solve_rooms(p, timing, remaining(0.4))
    if progress:
        progress("Gözetmenler atanıyor…")
    by_id = {e.id: e for e in p.exams}
    caps = {r.id: r.capacity for r in p.rooms}
    names = {r.id: r.name for r in p.rooms}
    seats = {}
    for eid, rids in rooms.items():
        for rid, n in zip(rids, seat_split(by_id[eid].students, [caps[r] for r in rids])):
            seats[eid, rid] = n
    proctors = _solve_proctors(p, timing, rooms, seats, remaining(0.9))
    needs = _needs(p, _units(p, timing, rooms), seats)

    result = Result("ok")
    for eid, t0 in timing.items():
        e = by_id[eid]
        rids = rooms.get(eid, [])
        rows = []
        for rid in rids:
            duty = proctors.get((eid, rid), [])
            rows.append((rid, seats[eid, rid], [t for t, _r in duty], {t: r for t, r in duty if r != "G"}))
            need, _locked = needs[eid, rid]
            for role, want in need.items():
                got = sum(1 for _t, r in duty if r == role)
                if got < want and role == "T" and p.carriers_per_session:
                    result.warnings.append(f"{_slot_label(p, t0)} oturumu: {want} taşıyıcı gerekli, {got} atanabildi "
                                           "(taşıyıcı olabilen müsait personel yok).")
                elif got < want:
                    result.warnings.append(f"«{e.name}» – {names[rid]}: {want} {ROLE_LABELS.get(role, role)} gerekli, "
                                           f"{got} atanabildi (müsait öğretmen yok).")
        result.placements[eid] = (t0, rows)
        if not rids:
            result.warnings.append(f"«{e.name}» ({_slot_label(p, t0)}): uygun salon bulunamadı.")
    empty = [e for e in p.exams if not e.students]
    if empty:
        result.warnings.insert(0, f"{len(empty)} sınavın öğrenci sayısı 0 (sınıfların öğrenci sayısı girilmemiş olabilir); "
                                  "bu sınavlara tek salon verildi" + (
                                      ". Görev rolleri öğrenci sayısına göre hesaplandığından bu salonlara yalnızca 1 "
                                      "gözetmen verildi (salon amiri ve taşıyıcı yok); kontenjanı “Ders sınav bilgileri” "
                                      "sayfasından aktarın." if p.duty_roles else "."))
    result.unplaced = [e.id for e in p.exams if e.id not in timing]
    for eid in result.unplaced:
        e = by_id[eid]
        k = _min_rooms(p, e)
        if k * 2 > len(p.rooms):
            why = (f"{e.students} öğrenci için en az {k}/{len(p.rooms)} salon gerekiyor; bu kadar salonun ve "
                   f"{len(e.classes)} sınıfının birlikte boş olduğu oturum kalmadı. Sınavı bölün, salon ekleyin ya da sınav "
                   "kapasitesi oranını artırın.")
        else:
            why = ("sınıflarının diğer sınavları, günlük sınır, salon kapasitesi ya da gözetmen sayısı bu sınava boş oturum "
                   "bırakmadı. Günleri/oturumları çoğaltmayı ya da süre sınırını artırmayı deneyin.")
        result.warnings.append(f"«{e.name}» yerleştirilemedi: {why}")
    if result.unplaced or any("salon bulunamadı" in w or "gözetmen gerekli" in w for w in result.warnings):
        result.status = "partial"
    loads = {}
    for _t0, rows in result.placements.values():
        for row in rows:
            for t in row[2]:
                loads[t] = loads.get(t, 0) + 1
    result.stats = {
        "exams": len(p.exams), "placed": len(timing), "rooms_used": sum(len(r) for r in rooms.values()),
        "proctor_max": max(loads.values(), default=0), "proctor_teachers": len(loads),
        "seconds": round(time.monotonic() - started, 1),
    }
    return result
