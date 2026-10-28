"""Gelişmiş kart ilişkileri (aSc'deki gelişmiş liste): çözücü kısıtları ve sonradan denetim.

encode() CP-SAT modeline kısıt ekler; check() bir yerleşimdeki ihlalleri metin olarak döner.
Her koşul bir kart kümesine (keys) uygulanır; iki taraflı koşullarda B kümesi keys_b'dir.
"""

from collections import defaultdict
from itertools import combinations

# Koşul kümeleri
DAY_RULES = {
    "day_span_max", "day_span_min", "min_per_day", "min_gap_length", "min_distance", "gaps_from_start", "gaps_to_end",
    "max_gaps_week", "gaps_week_from_start", "gaps_week_to_end", "max_consec_days", "max_free_days",
}
AB_RULES = {
    "ab_after", "ab_before", "ab_not_mixed", "ab_week_before", "ab_day_before", "ab_max_consecutive", "ab_fill_gaps",
    "ab_a_first", "ab_b_after", "ab_not_followed",
}
EDGE_RULES = {"only_in_map", "no_start_at", "no_end_at", "first_or_last", "reserve"}
COUNT_RULES = {
    "max_subjects_week", "max_subjects_day", "max_teachers_day", "max_rooms_day", "max_room_changes",
    "max_building_changes", "max_buildings_week", "max_rooms_position",
}
ALL = DAY_RULES | AB_RULES | EDGE_RULES | COUNT_RULES


# --- çözücü ------------------------------------------------------------------------------------

def _is_var(t):
    return not isinstance(t, int)


def _empties(m, row, name, mode):
    """Günlük boş hücre göstergeleri (alttan sınırlı; yalnızca üst sınır için).
    mode: "inner" iki ders arası, "lead" ilk dersten önce dahil, "trail" son dersten sonra dahil."""
    P = len(row)
    if not any(_is_var(b) for b in row):
        return []
    before, after = [0] * P, [0] * P
    for s in range(1, P):
        before[s] = m.NewBoolVar(f"{name}_b{s}")
        m.Add(before[s] >= row[s - 1])
        m.Add(before[s] >= before[s - 1])
    for s in range(P - 2, -1, -1):
        after[s] = m.NewBoolVar(f"{name}_a{s}")
        m.Add(after[s] >= row[s + 1])
        m.Add(after[s] >= after[s + 1])
    out = []
    for s in range(P):
        e = m.NewBoolVar(f"{name}_e{s}")
        if mode == "inner":
            m.Add(e >= before[s] + after[s] - 1 - row[s])
        elif mode == "lead":
            m.Add(e >= after[s] - row[s])
        else:
            m.Add(e >= before[s] - row[s])
        out.append(e)
    return out


def _and(m, a, b, name):
    """a ve b birlikte 1 ise 1 olan bool (sabitler sadeleştirilir)."""
    if not _is_var(a) or not _is_var(b):
        const, other = (a, b) if not _is_var(a) else (b, a)
        return other if const else 0
    v = m.NewBoolVar(name)
    m.Add(v <= a)
    m.Add(v <= b)
    m.Add(v >= a + b - 1)
    return v


def encode(b, rel, g, keys, keys_b, ctx):
    """b: çözücü kurucusu (_Builder); ctx: limit/at_least/violation/busy/any/in_map yardımcıları."""
    m, D, P = b.m, b.problem.days, b.problem.periods
    cond, n = rel.condition, rel.param
    tag = f"x{g}"

    def row(ks, d, t=tag):
        return [ctx.busy(ks, d, s, t) for s in range(P)]

    def forbid(pos, neg, label):
        """pos'un hepsi 1 ve neg'in hepsi 0 olamaz (ihlal göstergesiyle)."""
        if any(not _is_var(t) and t == 0 for t in pos) or not any(_is_var(t) for t in pos + neg):
            return  # olamayacak durum ya da yalnızca sabitler
        v = ctx.violation(label)
        m.Add(sum(pos) - sum(neg) <= len(pos) - 1 + v)

    def day_used(ks, d, t):
        return ctx.any(b._day_terms(ks, d), f"{ctx.name}_{t}{g}_{d}")

    if cond == "day_span_max":
        for d in range(D):
            r = row(keys, d)
            for s in range(P):
                for t in range(s + n, P):
                    forbid([r[s], r[t]], [], f"{g}_{d}_{s}_{t}")
    elif cond == "day_span_min":
        if n <= 1:
            return
        for d in range(D):
            r = row(keys, d)
            if not any(_is_var(x) for x in r):
                continue
            pairs = [_and(m, r[s], r[t], f"{ctx.name}_sp{g}_{d}_{s}_{t}") for s in range(P) for t in range(s + n - 1, P)]
            ctx.at_least(pairs, 1, f"{g}_{d}", condition=ctx.any(r, f"{ctx.name}_spany{g}_{d}"))
    elif cond == "min_per_day":
        for d in range(D):
            ctx.at_least([x for s, x in enumerate(row(keys, d)) if ctx.in_map((d, s))], n, f"{g}_{d}")
    elif cond == "min_gap_length":
        for d in range(D):
            r = row(keys, d)
            for length in range(1, n):
                for s in range(1, P - length):
                    forbid([r[s - 1], r[s + length]], r[s : s + length], f"{g}_{d}_{s}_{length}")
    elif cond == "min_distance":
        cards = b.problem.cards
        for a, c in combinations(keys, 2):
            la, lc = cards[a].length, cards[c].length
            v = None
            for (d, p), xa in b.x[a].items():
                for (e, q), xc in b.x[c].items():
                    if d != e:
                        continue
                    gap = q - (p + la) if q >= p + la else (p - (q + lc) if p >= q + lc else None)
                    if gap is not None and gap < n:
                        v = v if v is not None else ctx.violation(f"{g}_{a}_{c}")
                        m.Add(xa + xc <= 1 + v)
    elif cond in ("gaps_from_start", "gaps_to_end"):
        mode = "lead" if cond == "gaps_from_start" else "trail"
        for d in range(D):
            ctx.limit(_empties(m, row(keys, d), f"{ctx.name}_e{g}_{d}", mode), n, f"{g}_{d}")
    elif cond in ("max_gaps_week", "gaps_week_from_start", "gaps_week_to_end"):
        mode = {"max_gaps_week": "inner", "gaps_week_from_start": "lead", "gaps_week_to_end": "trail"}[cond]
        terms = [e for d in range(D) for e in _empties(m, row(keys, d), f"{ctx.name}_w{g}_{d}", mode)]
        ctx.limit(terms, n, f"{g}")
    elif cond == "max_consec_days":
        used = [day_used(keys, d, "cd") for d in range(D)]
        for s in range(D - n):
            ctx.limit(used[s : s + n + 1], n, f"{g}_{s}")
    elif cond == "max_free_days":
        used = [day_used(keys, d, "fd") for d in range(D)]
        for s in range(1, D - n - 1):  # s..s+n boş ve öncesinde/sonrasında ders olamaz
            before = ctx.any(used[:s], f"{ctx.name}_fb{g}_{s}")
            after = ctx.any(used[s + n + 1 :], f"{ctx.name}_fa{g}_{s}")
            forbid([before, after], used[s : s + n + 1], f"{g}_{s}")
    elif cond in AB_RULES:
        _encode_ab(b, rel, g, keys, keys_b, ctx, row, forbid, day_used)
    elif cond in ("no_start_at", "no_end_at", "first_or_last"):
        terms = []
        for k in keys:
            length = b.problem.cards[k].length
            for (d, p), x in b.x[k].items():
                if cond == "no_start_at" and ctx.in_map((d, p)):
                    terms.append(x)
                elif cond == "no_end_at" and ctx.in_map((d, p + length - 1)):
                    terms.append(x)
                elif cond == "first_or_last" and p != 0 and p + length != P:
                    terms.append(x)
        ctx.limit(terms, 0, f"{g}")
    elif cond == "only_in_map":
        terms = [v for k in keys for cell, vs in b.occ[k].items() if not ctx.in_map(cell) for v in vs]
        ctx.limit(terms, 0, f"{g}")
    elif cond == "reserve":
        terms = [v for k in keys_b for cell, vs in b.occ[k].items() if ctx.in_map(cell) for v in vs]
        ctx.limit(terms, 0, f"{g}")
    elif cond in COUNT_RULES:
        _encode_counts(b, rel, g, keys, ctx)


def _encode_ab(b, rel, g, keys, keys_b, ctx, row, forbid, day_used):
    m, D, P = b.m, b.problem.days, b.problem.periods
    cond, n = rel.condition, rel.param
    if cond == "ab_max_consecutive":
        both = list(keys) + list(keys_b)
        for d in range(D):
            r = row(both, d, f"ab{g}")
            for s in range(P - n):
                ctx.limit(r[s : s + n + 1], n, f"{g}_{d}_{s}")
        return
    if cond == "ab_day_before":
        has_a = [day_used(keys, d, "da") for d in range(D)]
        has_b = [day_used(keys_b, d, "db") for d in range(D)]
        for d in range(D):
            for e in range(d + 1):
                forbid([has_a[d], has_b[e]], [], f"{g}_{d}_{e}")
        return
    if cond == "ab_week_before":
        flat_a = [x for d in range(D) for x in row(keys, d, f"a{g}")]
        flat_b = [x for d in range(D) for x in row(keys_b, d, f"b{g}")]
        for j, xa in enumerate(flat_a):
            for i in range(j + 1):
                forbid([xa, flat_b[i]], [], f"{g}_{j}_{i}")
        return
    for d in range(D):
        A, B = row(keys, d, f"a{g}"), row(keys_b, d, f"b{g}")
        if cond == "ab_after":  # her A, her B'den sonra: A s'de ve B t>=s'de olamaz
            for s in range(P):
                for t in range(s, P):
                    forbid([A[s], B[t]], [], f"{g}_{d}_{s}_{t}")
        elif cond == "ab_before":
            for s in range(P):
                for t in range(s, P):
                    forbid([B[s], A[t]], [], f"{g}_{d}_{s}_{t}")
        elif cond == "ab_not_mixed":
            for s, t, u in combinations(range(P), 3):
                forbid([A[s], B[t], A[u]], [], f"{g}_{d}_{s}_{t}_{u}a")
                forbid([B[s], A[t], B[u]], [], f"{g}_{d}_{s}_{t}_{u}b")
        elif cond == "ab_fill_gaps":
            for s, t, u in combinations(range(P), 3):
                forbid([A[s], A[u]], [A[t], B[t]], f"{g}_{d}_{s}_{t}_{u}")
        elif cond == "ab_a_first":
            for t in range(P):
                forbid([B[t]], A[:t], f"{g}_{d}_{t}")
        elif cond == "ab_b_after":
            for s in range(P):
                forbid([A[s]], B[s + 1 :], f"{g}_{d}_{s}")
        elif cond == "ab_not_followed":
            for s in range(P - 1):
                forbid([A[s], B[s + 1]], [], f"{g}_{d}_{s}")


def _encode_counts(b, rel, g, keys, ctx):
    m, D, P = b.m, b.problem.days, b.problem.periods
    cond, n = rel.condition, rel.param
    cards = b.problem.cards
    name = f"{ctx.name}_c{g}"

    def flag(terms, label):
        if any(not _is_var(t) and t for t in terms):
            return 1
        terms = [t for t in terms if _is_var(t)]
        if not terms:
            return 0
        f = m.NewBoolVar(label)
        for t in terms:
            m.Add(f >= t)
        return f

    group = set(keys)
    if cond == "max_subjects_week":
        by_subject = defaultdict(list)
        for k in keys:
            by_subject[cards[k].subject] += [v for cell, vs in b.occ[k].items() if ctx.in_map(cell) for v in vs]
        ctx.limit([flag(t, f"{name}_s{s}") for s, t in by_subject.items()], n, f"{g}")
    elif cond in ("max_subjects_day", "max_teachers_day"):
        for d in range(D):
            by = defaultdict(list)
            for k in keys:
                owners = [cards[k].subject] if cond == "max_subjects_day" else cards[k].teachers
                for o in owners:
                    by[o] += b._day_terms([k], d)
            ctx.limit([flag(t, f"{name}_{d}_{o}") for o, t in by.items()], n, f"{g}_{d}")
    elif cond in ("max_rooms_day", "max_room_changes", "max_building_changes"):
        building = b.problem.room_building
        for d in range(D):
            by = defaultdict(list)
            for room, usage in b.room_usage.items():
                owner = room if cond != "max_building_changes" else building.get(room)
                if owner is None:
                    continue
                by[owner] += [u for (k, cell), u in usage.items() if k in group and cell[0] == d]
            limit = n if cond == "max_rooms_day" else n + 1  # değişim = farklı derslik/bina − 1
            ctx.limit([flag(t, f"{name}_{d}_{o}") for o, t in by.items()], limit, f"{g}_{d}")
    elif cond == "max_buildings_week":
        by = defaultdict(list)
        for room, usage in b.room_usage.items():
            owner = b.problem.room_building.get(room)
            if owner is not None:
                by[owner] += [u for (k, _), u in usage.items() if k in group]
        ctx.limit([flag(t, f"{name}_b{o}") for o, t in by.items()], n, f"{g}")
    elif cond == "max_rooms_position":
        by_cell = defaultdict(list)
        for room, usage in b.room_usage.items():
            for (k, cell), u in usage.items():
                if k in group:
                    by_cell[cell].append(u)
        for cell, terms in by_cell.items():
            if len(terms) > n:
                ctx.limit(terms, n, f"{g}_{cell[0]}_{cell[1]}")


# --- denetim -----------------------------------------------------------------------------------

def check(problem, placements, rel, keys, keys_b, add):
    """Yerleşimdeki ihlalleri add(metin) ile bildirir."""
    D, P = problem.days, problem.periods
    cond, n = rel.condition, rel.param
    cards = problem.cards

    def cells(ks, cell_filter=None):
        out = defaultdict(set)
        for k in ks:
            pl = placements.get(k)
            if pl is None:
                continue
            for d, p in cards[k].cells(pl.day, pl.period):
                if cell_filter is None or (d, p) in cell_filter:
                    out[d].add(p)
        return out

    def holes(periods, mode):
        if not periods:
            return 0
        lo, hi = min(periods), max(periods)
        inner = (hi - lo + 1) - len(periods)
        return inner + (lo if mode == "lead" else 0) + (P - 1 - hi if mode == "trail" else 0)

    day = lambda d: f"gün {d + 1}"  # noqa: E731
    by_day = cells(keys)
    if cond == "day_span_max":
        for d, ps in by_day.items():
            if max(ps) - min(ps) + 1 > n:
                add(f"{day(d)}: zaman harcaması {max(ps) - min(ps) + 1} saat (en fazla {n}).")
    elif cond == "day_span_min":
        for d, ps in by_day.items():
            if max(ps) - min(ps) + 1 < n:
                add(f"{day(d)}: zaman harcaması {max(ps) - min(ps) + 1} saat (en az {n}).")
    elif cond == "min_per_day":
        for d in range(D):
            count = len(cells(keys, rel.cells).get(d, ()))
            if count < n:
                add(f"{day(d)}: {count} saat (en az {n}).")
    elif cond == "min_gap_length":
        for d, ps in by_day.items():
            ordered = sorted(ps)
            short = [b - a - 1 for a, b in zip(ordered, ordered[1:]) if 1 < b - a <= n]
            if short:
                add(f"{day(d)}: {min(short)} saatlik boşluk (en az {n}).")
    elif cond == "min_distance":
        spans = defaultdict(list)
        for k in keys:
            pl = placements.get(k)
            if pl is not None:
                spans[pl.day].append((pl.period, pl.period + cards[k].length))
        for d, items in spans.items():
            items.sort()
            for (s1, e1), (s2, e2) in zip(items, items[1:]):
                if s2 >= e1 and s2 - e1 < n:
                    add(f"{day(d)}: iki kart arasında {s2 - e1} boş saat (en az {n}).")
    elif cond in ("gaps_from_start", "gaps_to_end"):
        mode = "lead" if cond == "gaps_from_start" else "trail"
        for d, ps in by_day.items():
            if holes(ps, mode) > n:
                add(f"{day(d)}: {holes(ps, mode)} boş saat (en fazla {n}).")
    elif cond in ("max_gaps_week", "gaps_week_from_start", "gaps_week_to_end"):
        mode = {"max_gaps_week": "inner", "gaps_week_from_start": "lead", "gaps_week_to_end": "trail"}[cond]
        total = sum(holes(ps, mode) for ps in by_day.values())
        if total > n:
            add(f"haftada {total} boş saat (en fazla {n}).")
    elif cond == "max_consec_days":
        run = best = 0
        for d in range(D):
            run = run + 1 if d in by_day else 0
            best = max(best, run)
        if best > n:
            add(f"art arda {best} ders günü (en fazla {n}).")
    elif cond == "max_free_days":
        used = sorted(by_day)
        for a, b in zip(used, used[1:]):
            if b - a - 1 > n:
                add(f"{day(a)} ile {day(b)} arasında {b - a - 1} boş gün (en fazla {n}).")
    elif cond in AB_RULES:
        _check_ab(problem, rel, by_day, cells(keys_b), add)
    elif cond in ("no_start_at", "no_end_at", "first_or_last"):
        for k in keys:
            pl = placements.get(k)
            if pl is None:
                continue
            end = pl.period + cards[k].length - 1
            bad = (cond == "no_start_at" and (pl.day, pl.period) in (rel.cells or ())) or (
                cond == "no_end_at" and (pl.day, end) in (rel.cells or ())) or (
                cond == "first_or_last" and pl.period != 0 and end != P - 1)
            if bad:
                add(f"{day(pl.day)}, {pl.period + 1}. saatte başlayan kart kurala uymuyor.")
    elif cond == "only_in_map":
        for k in keys:
            pl = placements.get(k)
            if pl is not None and rel.cells is not None and not set(cards[k].cells(pl.day, pl.period)) <= rel.cells:
                add(f"{day(pl.day)}, {pl.period + 1}. saatteki kart işaretli saatlerin dışında.")
    elif cond == "reserve":
        used = cells(keys_b, rel.cells)
        for d, ps in used.items():
            add(f"{day(d)}, {min(ps) + 1}. saat: rezerv saate başka ders konmuş.")
    elif cond in COUNT_RULES:
        _check_counts(problem, placements, rel, keys, add)


def _check_ab(problem, rel, A, B, add):
    D, P = problem.days, problem.periods
    cond, n = rel.condition, rel.param
    if cond == "ab_max_consecutive":
        for d in range(D):
            both = A.get(d, set()) | B.get(d, set())
            run = best = 0
            for s in range(P):
                run = run + 1 if s in both else 0
                best = max(best, run)
            if best > n:
                add(f"gün {d + 1}: A ve B art arda {best} saat (en fazla {n}).")
        return
    if cond == "ab_day_before":
        if A and B and max(A) >= min(B):
            add("A'nın bir günü B'nin bir gününden önce değil.")
        return
    if cond == "ab_week_before":
        a = [(d, p) for d, ps in A.items() for p in ps]
        b = [(d, p) for d, ps in B.items() for p in ps]
        if a and b and max(a) >= min(b):
            add("hafta içinde bir A dersi bir B dersinden sonra.")
        return
    for d in range(D):
        a, b = sorted(A.get(d, ())), sorted(B.get(d, ()))
        text = None
        if cond == "ab_after" and a and b and min(a) <= max(b):
            text = "A dersleri B'den sonra değil"
        elif cond == "ab_before" and a and b and max(a) >= min(b):
            text = "A dersleri B'den önce değil"
        elif cond == "ab_not_mixed" and any(
            (x in a and y in b and z in a) or (x in b and y in a and z in b) for x, y, z in combinations(range(P), 3)
        ):
            text = "A ve B dersleri karışık"
        elif cond == "ab_fill_gaps" and a:
            missing = [s for s in range(min(a), max(a)) if s not in a and s not in b]
            if missing:
                text = f"A'nın {missing[0] + 1}. saatteki boşluğu B ile dolmamış"
        elif cond == "ab_a_first" and b and not (a and min(a) < min(b)):
            text = "B'den önce A yok"
        elif cond == "ab_b_after" and a and not (b and max(b) > max(a)):
            text = "A'dan sonra B yok"
        elif cond == "ab_not_followed" and any(s + 1 in b for s in a):
            text = "A'nın hemen ardından B geliyor"
        if text:
            add(f"gün {d + 1}: {text}.")


def _check_counts(problem, placements, rel, keys, add):
    cond, n = rel.condition, rel.param
    cards = problem.cards
    placed = [k for k in keys if k in placements]
    if cond == "max_subjects_week":
        subjects = {cards[k].subject for k in placed
                    if rel.cells is None or set(cards[k].cells(placements[k].day, placements[k].period)) & rel.cells}
        if len(subjects) > n:
            add(f"{len(subjects)} farklı ders (en fazla {n}).")
        return
    if cond == "max_rooms_position":
        per_cell = defaultdict(int)
        for k in placed:
            pl = placements[k]
            for cell in cards[k].cells(pl.day, pl.period):
                per_cell[cell] += len(pl.rooms)
        for (d, p), count in per_cell.items():
            if count > n:
                add(f"gün {d + 1}, saat {p + 1}: {count} derslik (en fazla {n}).")
        return
    if cond == "max_buildings_week":
        buildings = {problem.room_building.get(r) for k in placed for r in placements[k].rooms} - {None}
        if len(buildings) > n:
            add(f"haftada {len(buildings)} farklı bina (en fazla {n}).")
        return
    per_day = defaultdict(set)
    for k in placed:
        pl = placements[k]
        if cond == "max_subjects_day":
            per_day[pl.day].add(cards[k].subject)
        elif cond == "max_teachers_day":
            per_day[pl.day].update(cards[k].teachers)
        elif cond in ("max_rooms_day", "max_room_changes"):
            per_day[pl.day].update(pl.rooms)
        else:
            per_day[pl.day].update(problem.room_building.get(r) for r in pl.rooms if problem.room_building.get(r) is not None)
    limit = n if cond in ("max_subjects_day", "max_teachers_day", "max_rooms_day") else n + 1
    for d, items in per_day.items():
        if len(items) > limit:
            what = {"max_subjects_day": "farklı ders", "max_teachers_day": "farklı öğretmen", "max_rooms_day": "farklı derslik",
                    "max_room_changes": "derslik değişimi", "max_building_changes": "bina değişimi"}[cond]
            count = len(items) if limit == n else len(items) - 1
            add(f"gün {d + 1}: {count} {what} (en fazla {n}).")
