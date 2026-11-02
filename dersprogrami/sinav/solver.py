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

Her aşamada açgözlü bir başlangıç çözümü ipucu olarak verilir; CP-SAT süre içinde çözüm bulamazsa o kullanılır.
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
    locked_proctors: dict = field(default_factory=dict)  # {salon: (öğretmen, ...)}
    student_ids: frozenset = frozenset()


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

    @property
    def n_slots(self):
        return self.n_days * self.n_sessions


@dataclass
class Result:
    status: str                       # ok / partial / failed
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # {sınav: (başlangıç dilimi, [(salon, oturan, [öğretmen, ...]), ...])}
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
    if p.proctors_per_room and not p.proctors:
        errors.append("Gözetmen olabilecek öğretmen yok (hepsi muaf).")
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
    free = [sum(1 for tch in p.proctors if t not in (p.unavailable.get(tch) or ())) for t in range(T)]
    seats, rooms, proctors = [0] * T, [0] * T, [0] * T
    class_busy, class_day = set(), {}
    out = {}
    order = sorted(range(len(p.exams)), key=lambda i: (p.exams[i].fixed is None, -need[p.exams[i].id],
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
            if p.proctors_per_room and any(proctors[s] + k * p.proctors_per_room > free[s] for s in span):
                continue
            load = max(rooms[s] for s in span) + sum(class_day.get((c, t // S), 0) for c in e.classes) * 2
            if best is None or load < best[0]:
                best = (load, t)
        if best is None:
            continue
        t = best[1]
        out[i] = t
        for s in range(t, t + e.duration):
            seats[s] += e.students
            rooms[s] += k
            proctors[s] += k * p.proctors_per_room
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
        if p.proctors_per_room:
            free = sum(1 for tch in p.proctors if t not in (p.unavailable.get(tch) or ()))
            m.Add(sum(v * need[p.exams[i].id] * p.proctors_per_room for i, v in cover[t]) <= free)

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


def _greedy_proctors(p, timing, rooms):
    by_id = {e.id: e for e in p.exams}
    ppr = p.proctors_per_room
    load = {t: 0 for t in p.proctors}
    busy = set()
    out = {}
    units = _units(p, timing, rooms)
    for eid, rid, slots in sorted(units, key=lambda u: (u[2][0], -len(by_id[u[0]].locked_proctors))):
        e = by_id[eid]
        locked = list(e.locked_proctors.get(rid, ()))
        chosen = [t for t in locked if t in load][:ppr] if locked else []
        if not locked:
            own = [t for t in e.teachers if t in load]
            pool = sorted(p.proctors, key=lambda t: (t not in own, load[t], t))
            for t in pool:
                if len(chosen) >= ppr:
                    break
                if any((t, s) in busy for s in slots) or not _available(p, t, slots):
                    continue
                chosen.append(t)
        for t in chosen:
            load[t] += len(slots)
            for s in slots:
                busy.add((t, s))
        out[eid, rid] = chosen
    return out


def _solve_proctors(p, timing, rooms, limit):
    ppr = p.proctors_per_room
    units = _units(p, timing, rooms)
    if not ppr or not units:
        return {(eid, rid): [] for eid, rid, _ in units}
    by_id = {e.id: e for e in p.exams}
    greedy = _greedy_proctors(p, timing, rooms)
    m = cp_model.CpModel()
    w, obj = {}, []
    per_slot = {}
    loads = {t: [] for t in p.proctors}
    day_loads = {}
    for u, (eid, rid, slots) in enumerate(units):
        e = by_id[eid]
        locked = [t for t in e.locked_proctors.get(rid, ()) if t in loads]
        terms = []
        for tch in p.proctors:
            if locked and tch not in locked:
                continue
            if not locked and not _available(p, tch, slots):
                continue
            v = m.NewBoolVar(f"w{u}_{tch}")
            w[u, tch] = v
            m.AddHint(v, int(tch in greedy.get((eid, rid), ())))
            if locked:
                m.Add(v == 1)
            terms.append(v)
            loads[tch].append(v * len(slots))
            for s in slots:
                per_slot.setdefault((tch, s), []).append(v)
            day_loads.setdefault((tch, slots[0] // p.n_sessions), []).append(v * len(slots))
        short = m.NewIntVar(0, ppr, f"short{u}")
        m.Add(sum(terms) + short == (len(locked) if locked else ppr))
        obj.append(W_SHORT * short)
    for terms in per_slot.values():
        if len(terms) > 1:
            m.Add(sum(terms) <= 1)
    # dersin öğretmeni kendi sınavında
    for eid in rooms:
        e = by_id[eid]
        if not e.teachers:
            continue
        terms = [w[u, t] for u, (e2, _r, _s) in enumerate(units) if e2 == eid for t in e.teachers if (u, t) in w]
        if terms:
            own = m.NewBoolVar(f"own{eid}")
            m.Add(own <= sum(terms))
            obj.append(W_OWN * (1 - own))
    total = sum(len(s) for _e, _r, s in units) * ppr
    target = math.ceil(total / max(1, len(p.proctors)))
    max_load = m.NewIntVar(0, total, "maxload")
    obj.append(W_MAX_LOAD * max_load)
    for tch, terms in loads.items():
        if not terms:
            continue
        m.Add(max_load >= sum(terms))
        over = m.NewIntVar(0, total, f"over{tch}")
        m.Add(over >= sum(terms) - target)
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
    out = {}
    for u, (eid, rid, _s) in enumerate(units):
        out[eid, rid] = [t for t in p.proctors if (u, t) in w and solver.Value(w[u, t])]
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
    proctors = _solve_proctors(p, timing, rooms, remaining(0.9))

    by_id = {e.id: e for e in p.exams}
    caps = {r.id: r.capacity for r in p.rooms}
    names = {r.id: r.name for r in p.rooms}
    result = Result("ok")
    for eid, t0 in timing.items():
        e = by_id[eid]
        rids = rooms.get(eid, [])
        seats = seat_split(e.students, [caps[r] for r in rids])
        result.placements[eid] = (t0, [(rid, seats[k], proctors.get((eid, rid), [])) for k, rid in enumerate(rids)])
        if not rids:
            result.warnings.append(f"«{e.name}» ({_slot_label(p, t0)}): uygun salon bulunamadı.")
        for rid in rids:
            got = len(proctors.get((eid, rid), []))
            want = len(e.locked_proctors.get(rid, ())) or p.proctors_per_room
            if got < want:
                result.warnings.append(f"«{e.name}» – {names[rid]}: {want} gözetmen gerekli, {got} atanabildi (müsait öğretmen yok).")
    empty = [e for e in p.exams if not e.students]
    if empty:
        result.warnings.insert(0, f"{len(empty)} sınavın öğrenci sayısı 0 (sınıfların öğrenci sayısı girilmemiş olabilir); "
                                  "bu sınavlara tek salon verildi.")
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
        for _rid, _seats, teachers in rows:
            for t in teachers:
                loads[t] = loads.get(t, 0) + 1
    result.stats = {
        "exams": len(p.exams), "placed": len(timing), "rooms_used": sum(len(r) for r in rooms.values()),
        "proctor_max": max(loads.values(), default=0), "proctor_teachers": len(loads),
        "seconds": round(time.monotonic() - started, 1),
    }
    return result
