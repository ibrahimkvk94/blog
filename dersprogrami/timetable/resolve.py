"""Çözüm merkezi: kalıcı program değişikliği için en az kartı oynatan öneriler.

İstek türleri:
- shift:   kart bulunduğu saatten çıksın (isteğe bağlı: yalnızca aynı gün içinde)
- place:   kart belirtilen gün/saate gelsin
- teacher: öğretmen belirtilen saatlerde gelemiyor (o saatlerdeki dersleri kayar)
- room:    derslik belirtilen saatlerde kullanılamıyor
- insert:  yerleşmemiş (bekleyen) kart uygun bir saate girsin; gerekirse diğerleri yer açsın

Yöntem: yayındaki/seçili program olduğu gibi alınır. Hedef kartlar ve "komşuları" (aynı öğretmen,
sınıf/grup ya da derslikteki kartlar) serbest bırakılır, diğer tüm kartlar yerinde sabitlenir.
Çözücü yerinden ayrılan her kartı cezalandırır; böylece en az değişiklikli çözüm bulunur. Çözüm
çıkmazsa komşuluk bir halka genişletilir. Bulunan her çözüm yasaklanıp yeniden çözülerek birbirinden
farklı öneriler üretilir. Mevcut çakışmalı kartlar da serbest bırakılır (sabitlenirse çözüm olmaz).
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field, replace

from django.db import transaction
from django.utils import timezone

from . import editing, versions
from .models import Availability, Card, Substitution
from .refs import DAY_SHORT, ref_index
from .solver import cpsat
from .solver.builder import build_problem
from .solver.problem import Problem
from .solver.validate import validate
from .services import placements_of

RING_LIMITS = (6, 10, 16, 25)  # halka başına çözüm süresi (sn)
# Programı iyileştirme: hedef öğretmenin boşluk saati ve okula geldiği gün başına ceza; oynatılan
# ders başına ceza bunlardan küçüktür, böylece yalnızca kaliteyi artıran hareketler yapılır.
IMPROVE_GAP, IMPROVE_DAY, IMPROVE_MOVE = 40, 30, 12


class ResolveError(Exception):
    pass


@dataclass
class Request:
    kind: str  # shift | place | teacher | room | insert
    card_ids: list = field(default_factory=list)
    teacher_id: int | None = None
    room_id: int | None = None
    day: int | None = None
    periods: list = field(default_factory=list)  # teacher/room: kapanan saatler; place: [hedef saat]
    same_day: bool = False
    max_moves: int = 4
    alternatives: int = 3


def _where(day, period, length):
    if day is None:
        return "yerleşmemiş"
    end = f"–{period + length}" if length > 1 else ""
    return f"{DAY_SHORT[day]} {period + 1}{end}"


def _subproblem(problem, keep):
    """Yalnızca keep'teki kartlarla yeni problem; kart anahtarları ve ilişki kümeleri yeniden eşlenir."""
    keys = sorted(keep)
    new_key = {old: i for i, old in enumerate(keys)}
    cards = [replace(problem.cards[k], key=new_key[k]) for k in keys]
    rels = []
    for rel in problem.relationships:
        groups = [[new_key[k] for k in g if k in new_key] for g in rel.groups]
        groups_b = [[new_key[k] for k in g if k in new_key] for g in rel.groups_b]
        rels.append(replace(rel, groups=groups, groups_b=groups_b))
    sub = replace(problem, cards=cards, relationships=rels)
    return sub, new_key


def _resources(card, place):
    res = [("t", t) for t in card.teachers] + [("a", a) for a in card.atoms] + [("s", s) for s in card.students]
    if place is not None:
        res += [("r", r) for r in place.rooms]
    return res


def _conflicting(problem, placements):
    """Şu anki yerleşimde aynı kaynağı aynı anda kullanan kartlar."""
    occ = defaultdict(list)
    for card in problem.cards:
        place = placements.get(card.key)
        if place is None:
            continue
        for universe in card.universes:
            for cell in card.cells(place.day, place.period):
                for res in _resources(card, place):
                    occ[(res, universe, cell)].append(card.key)
    bad = set()
    for (res, _, _), keys in occ.items():
        limit = problem.room_slots.get(res[1], 1) if res[0] == "r" else 1
        if len(keys) > limit:
            bad.update(keys)
    return bad


def _neighbours(problem, placements, seeds):
    by_res = defaultdict(set)
    for card in problem.cards:
        for res in _resources(card, placements.get(card.key)):
            by_res[res].add(card.key)
    out = set(seeds)
    for k in seeds:
        card = problem.cards[k]
        for res in _resources(card, placements.get(k)):
            out |= by_res[res]
    return out


class Center:
    def __init__(self, timetable):
        self.timetable = timetable
        self.school = timetable.school
        self.full = build_problem(self.school, timetable=timetable)
        self.placements = placements_of(self.full, timetable)
        self.db_cards = {c.id: c for c in timetable.cards.select_related("lesson__subject", "classroom")
                         .prefetch_related("lesson__classes", "lesson__teachers", "lesson__groups")}
        self.key_of = {c.card_id: c.key for c in self.full.cards}

    # --- isteği probleme çevirme -----------------------------------------------------------

    def _targets(self, req):
        """Hedef kartlar ve onların izinli başlangıçları: {anahtar: başlangıç listesi}."""
        cards, placements = self.full.cards, self.placements
        allowed = {}
        if req.kind == "insert":
            for card_id in req.card_ids:
                k = self.key_of.get(card_id)
                if k is None:
                    raise ResolveError("Kart bu programda yok.")
                if k in placements:
                    raise ResolveError("Kart zaten yerleşmiş; taşımak için “Dersi kaydır”ı kullanın.")
                allowed[k] = list(cards[k].starts)
            return allowed
        if req.kind in ("shift", "place"):
            for card_id in req.card_ids:
                k = self.key_of.get(card_id)
                if k is None:
                    raise ResolveError("Kart bu programda yok.")
                card, place = cards[k], placements.get(k)
                if card.fixed is not None:
                    raise ResolveError(f"{self.full.label('lesson', card.lesson_id)} kilitli; önce kilidini açın.")
                if req.kind == "shift":
                    if place is None:
                        raise ResolveError("Kart zaten yerleşmemiş; bekleyenleri yerleştir'i kullanın.")
                    starts = [s for s in card.starts if s != (place.day, place.period)]
                    if req.same_day:
                        starts = [s for s in starts if s[0] == place.day]
                else:
                    target = (req.day, req.periods[0])
                    if target not in card.starts:
                        raise ResolveError(f"{_where(*target, card.length)} bu kart için kapalı ya da gün sonunu aşıyor.")
                    starts = [target]
                allowed[k] = starts
        elif req.kind == "teacher":
            closed = {(req.day, p) for p in req.periods}
            for card in cards:
                place = placements.get(card.key)
                if req.teacher_id not in card.teachers or place is None:
                    continue
                if not set(card.cells(place.day, place.period)) & closed:
                    # Kapanan saatlere değmiyor ama oraya da taşınamamalı.
                    card.starts = [st for st in card.starts if not set(card.cells(*st)) & closed]
                    continue
                if card.fixed is not None:
                    raise ResolveError(f"{self.full.label('lesson', card.lesson_id)} kilitli ve kapanan saate düşüyor.")
                allowed[card.key] = [s for s in card.starts if not set(card.cells(*s)) & closed]
        else:  # derslik: kapanan saatlerde o derslikteki kartlar başka saate ya da dersliğe geçer
            closed = {(req.day, p) for p in req.periods}
            self.full.room_blocked = {**self.full.room_blocked,
                                      req.room_id: frozenset(set(self.full.room_blocked.get(req.room_id, ())) | closed)}
            for card in cards:
                place = placements.get(card.key)
                if place is None or req.room_id not in place.rooms or not set(card.cells(place.day, place.period)) & closed:
                    continue
                if card.fixed is not None:
                    raise ResolveError(f"{self.full.label('lesson', card.lesson_id)} kilitli ve kapanan saatte bu derslikte.")
                allowed[card.key] = list(card.starts)
        if req.kind in ("teacher", "room") and not allowed:
            raise ResolveError("Seçilen saatlerde etkilenen ders yok.")
        return allowed

    # --- çözme -----------------------------------------------------------------------------

    def proposals(self, req):
        allowed = self._targets(req)
        for k, starts in allowed.items():
            if not starts:
                raise ResolveError(f"{self.full.label('lesson', self.full.cards[k].lesson_id)} için uygun başka saat yok (müsaitlik).")
        placed = {k for k in self.placements}
        keep = placed | set(allowed)
        conflicts = _conflicting(self.full, self.placements)
        baseline_v, baseline_stats = validate(self.full, self.placements)
        found, forbidden = [], []
        seeds = set(allowed) | conflicts
        ring = seeds
        for depth, limit in enumerate(RING_LIMITS):
            ring = set(keep) if depth == len(RING_LIMITS) - 1 else _neighbours(self.full, self.placements, ring)
            while len(found) < req.alternatives:
                result = self._solve(req, allowed, keep, ring, forbidden, limit)
                if result is None:
                    break
                moved_keys, placements = result
                forbidden.append(sorted(moved_keys))
                found.append(self._report(placements, moved_keys, baseline_v, baseline_stats))
            # Yeterli öneri yoksa bir halka daha dene; ama çözüm bulunduysa en fazla 2. halkaya kadar.
            if len(found) >= req.alternatives or (found and depth >= 1):
                break
        found.sort(key=lambda p: (p["new_violations_hard"], p["count"], p["score"]))
        return found

    def _solve(self, req, allowed, keep, free, forbidden, limit, tune=None):
        sub, new_key = _subproblem(self.full, keep)
        old_of = {v: k for k, v in new_key.items()}
        anchors, room_anchors = {}, {}
        for card in sub.cards:
            old = old_of[card.key]
            place = self.placements.get(old)
            if old in allowed:
                card.starts = allowed[old]
                card.fixed = None
            elif old not in free and place is not None:
                card.fixed, card.fixed_room, card.fixed_rooms = (place.day, place.period), place.room, place.rooms
            if place is not None:
                anchors[card.key] = (place.day, place.period)
                card.hint = (place.day, place.period, place.room)
                if place.rooms:
                    room_anchors[card.key] = tuple(place.rooms)
        sub.anchors = anchors
        sub.room_anchors = room_anchors
        sub.max_moves = req.max_moves
        sub.forbidden_move_sets = [[new_key[k] for k in s if k in new_key] for s in forbidden]
        if tune:
            tune(sub)
        solution = cpsat.solve(sub, time_limit=limit, mode=cpsat.RELAXED, workers=8, two_phase=False)
        if not solution.ok or solution.unplaced:
            return None
        placements = dict(self.placements)
        moved = set()
        for key, place in solution.placements.items():
            old = old_of[key]
            before = self.placements.get(old)
            if before is None or (before.day, before.period) != (place.day, place.period):
                moved.add(old)
            placements[old] = place
        return moved, placements

    # --- programı iyileştirme ---------------------------------------------------------------

    def improve(self, teacher_ids=(), class_ids=(), max_moves=12, time_limit=25, weights=(IMPROVE_GAP, IMPROVE_DAY), everyone=False):
        """Seçilen öğretmen/sınıfların boşluklarını ve öğretmenlerin okula geldiği gün sayısını en az
        ders oynatarak azaltan tek öneri. Yerleşmemiş kartlar bu işin konusu değildir."""
        full, placements = self.full, self.placements
        teacher_ids, class_ids = set(teacher_ids), set(class_ids)
        targets = {c.key for c in full.cards if c.key in placements and c.fixed is None
                   and (set(c.teachers) & teacher_ids or {full.atom_class(a) for a in c.atoms} & class_ids)}
        if not targets:
            raise ResolveError("Seçilenlerin oynatılabilir (yerleşmiş ve kilitsiz) dersi yok.")
        keep = set(placements)
        free = (_neighbours(full, placements, targets) | _conflicting(full, placements)) & keep
        req = Request("improve", max_moves=max_moves)
        # everyone: diğer öğretmenlerin boşluk/günü de aynı ağırlıkla sayılır (okul geneli iyileştirme)
        teacher_weights = {t: tuple(weights) for t in (self.school.teachers.values_list("id", flat=True) if everyone else teacher_ids)}

        def tune(sub):
            sub.anchor_weight = IMPROVE_MOVE
            sub.teacher_weights = teacher_weights

        baseline_v, baseline_stats = validate(full, placements)
        result = self._solve(req, {}, keep, free, [], time_limit, tune=tune)
        if result is None or not result[0]:
            return None
        moved_keys, after = result
        proposal = self._report(after, moved_keys, baseline_v, baseline_stats)
        if proposal["new_violations_hard"]:
            return None
        proposal["quality"] = self._quality_change(placements, after, teacher_ids, class_ids)
        self.last_after = after  # okul geneli iyileştirme sonraki adıma buradan devam eder
        return proposal

    def _quality_change(self, before, after, teacher_ids, class_ids):
        """Hedeflerin boşluk ve gün sayısı: önce / sonra (yalnızca değişenler)."""
        def metrics(placements):
            busy = defaultdict(lambda: defaultdict(set))
            for card in self.full.cards:
                place = placements.get(card.key)
                if place is None:
                    continue
                owners = [("t", t) for t in card.teachers if t in teacher_ids]
                owners += [("c", c) for c in {self.full.atom_class(a) for a in card.atoms} if c in class_ids]
                for owner in owners:
                    busy[owner][place.day].update(range(place.period, place.period + card.length))
            return {o: (sum(max(p) - min(p) + 1 - len(p) for p in days.values() if p), sum(1 for p in days.values() if p))
                    for o, days in busy.items()}

        b, a = metrics(before), metrics(after)
        names = {**{("t", t.id): t.full_name for t in self.school.teachers.filter(pk__in=teacher_ids)},
                 **{("c", c.id): c.short or c.name for c in self.school.classes.filter(pk__in=class_ids)}}
        rows = []
        for owner in sorted(set(b) | set(a), key=lambda o: names.get(o, "")):
            gb, db = b.get(owner, (0, 0))
            ga, da = a.get(owner, (0, 0))
            if (gb, db) != (ga, da):
                rows.append({"name": names.get(owner, "?"), "kind": owner[0], "gaps": [gb, ga], "days": [db, da]})
        return {"rows": rows, "gaps": [sum(r["gaps"][0] for r in rows), sum(r["gaps"][1] for r in rows)],
                "days": [sum(r["days"][0] for r in rows if r["kind"] == "t"), sum(r["days"][1] for r in rows if r["kind"] == "t")]}

    # --- rapor -----------------------------------------------------------------------------

    def _report(self, placements, moved_keys, baseline_v, baseline_stats):
        cards = self.full.cards
        after_v, after_stats = validate(self.full, placements)
        before_msgs = {v.message for v in baseline_v}
        after_msgs = {v.message for v in after_v}
        new_v = [v for v in after_v if v.message not in before_msgs]
        fixed_v = [v for v in baseline_v if v.message not in after_msgs]
        moves, teachers, classes = [], {}, {}
        room_names = {r.id: str(r) for r in self.school.classrooms.all()}
        for k in sorted(moved_keys | {k for k, p in placements.items() if self.placements.get(k) and p.rooms != self.placements[k].rooms}):
            card = cards[k]
            db = self.db_cards[card.card_id]
            lesson = db.lesson
            before, after = self.placements.get(k), placements[k]
            for t in lesson.teachers.all():
                teachers[t.id] = t.full_name
            for c in lesson.classes.all():
                classes[c.id] = c.short or c.name
            moves.append({
                "card_id": card.card_id,
                "lesson_id": lesson.id,
                "subject": lesson.subject.short or lesson.subject.name,
                "subject_name": lesson.subject.name,
                "classes": ", ".join(c.short or c.name for c in lesson.classes.all()),
                "teachers": ", ".join(t.full_name for t in lesson.teachers.all()),
                "from": _where(before.day, before.period, card.length) if before else "yerleşmemiş",
                "to": _where(after.day, after.period, card.length),
                "room_from": ", ".join(room_names.get(r, "?") for r in before.rooms) if before else "",
                "room_to": ", ".join(room_names.get(r, "?") for r in after.rooms),
                "time_moved": k in moved_keys,
                "state_from": [before.day, before.period, before.room, list(before.extra_rooms)] if before else None,
                "state_to": [after.day, after.period, after.room, list(after.extra_rooms)],
            })
        return {
            "moves": moves,
            "count": len(moved_keys),
            "teachers": sorted(teachers.values()),
            "classes": sorted(classes.values()),
            "new_violations": [v.message for v in new_v],
            "new_violations_hard": sum(1 for v in new_v if v.level == "hard"),
            "fixed_violations": [v.message for v in fixed_v],
            "teacher_gaps": (baseline_stats.get("teacher_gaps", 0), after_stats.get("teacher_gaps", 0)),
            "class_gaps": (baseline_stats.get("class_gaps", 0), after_stats.get("class_gaps", 0)),
            "refs": self._ref_changes(placements, moves),
            "substitutions": self._future_substitutions(moves),
            "score": len(moved_keys) * 10 + max(0, after_stats.get("class_gaps", 0) - baseline_stats.get("class_gaps", 0)),
        }

    def _ref_changes(self, placements, moves):
        """ÜYBS referansları saat sırasına bağlıdır: taşınan derslerde hangi ref hangi saate geçiyor."""
        refs = ref_index(self.school)
        lesson_ids = {m["lesson_id"] for m in moves}
        out = []
        for lesson_id in lesson_ids:
            keys = [c.key for c in self.full.cards if c.lesson_id == lesson_id]

            def hours(source):
                items = []
                for k in keys:
                    p = source.get(k)
                    if p is not None:
                        items += [(p.day, p.period + i) for i in range(self.full.cards[k].length)]
                return sorted(items)

            before, after = hours(self.placements), hours(placements)
            lesson = next(m for m in moves if m["lesson_id"] == lesson_id)
            for (lid, cls_id, ordinal), ref in refs.items():
                if lid != lesson_id or ordinal > len(before) or ordinal > len(after):
                    continue
                b, a = before[ordinal - 1], after[ordinal - 1]
                if b != a:
                    out.append(f"{lesson['subject']} ({lesson['classes']}) ref {ref}: {DAY_SHORT[b[0]]} {b[1] + 1} → {DAY_SHORT[a[0]]} {a[1] + 1}")
        return sorted(out)

    def _future_substitutions(self, moves):
        ids = [m["card_id"] for m in moves if m["time_moved"]]
        return Substitution.objects.filter(card_id__in=ids, absence__date__gte=timezone.localdate()).count()


# --- uygulama --------------------------------------------------------------------------------

def apply(timetable, proposal, label, user=None, save_availability=None, archive_week=True):
    """Öneriyi programa uygular. Kartlar öneri hesaplandığından beri değiştiyse ResolveError."""
    with transaction.atomic():
        ids = [m["card_id"] for m in proposal["moves"]]
        cards = {c.id: c for c in Card.objects.select_for_update().filter(timetable=timetable, pk__in=ids)}
        for m in proposal["moves"]:
            card = cards.get(m["card_id"])
            state = [card.day, card.period, card.classroom_id, list(card.extra_rooms or [])] if card else None
            if state != m["state_from"]:
                raise ResolveError("Program öneri hesaplandıktan sonra değişmiş; lütfen yeniden hesaplayın.")
        if archive_week and timetable.school.active_timetable_id == timetable.pk:
            from . import uybs
            from .models import WeekArchive

            week = uybs.monday(timezone.localdate())
            if not WeekArchive.objects.filter(school=timetable.school, week_start=week).exists():
                uybs.archive_week(timetable, week, user)  # bu haftanın ÜYBS kaydı eski haliyle kalsın
        editing.record(timetable, label, editing.snapshot(cards.values()))
        for m in proposal["moves"]:
            card = cards[m["card_id"]]
            card.day, card.period, card.classroom_id, extra = m["state_to"][0], m["state_to"][1], m["state_to"][2], m["state_to"][3]
            card.extra_rooms = extra
        Card.objects.bulk_update(cards.values(), ["day", "period", "classroom", "extra_rooms"])
        if save_availability:
            field, obj, day, periods = save_availability
            existing = {(a.day, a.period) for a in Availability.objects.filter(**{field: obj}, day=day, period__in=periods)}
            Availability.objects.filter(**{field: obj}, day=day, period__in=periods).update(state=Availability.NO)
            Availability.objects.bulk_create(
                Availability(school=timetable.school, day=day, period=p, state=Availability.NO, **{field: obj})
                for p in periods if (day, p) not in existing
            )
        versions.save_version(timetable, user=user, note=f"Çözüm merkezi: {label}"[:200])
    from .problem_cache import bump

    bump(timetable.school_id)


def notify_moves(timetable, proposal):
    """Yeri değişen derslerin öğretmenlerine e-posta. Dönüş: (gönderilen, hatalar)."""
    from django.core.mail import EmailMessage

    from . import notify

    if not notify.enabled():
        return 0, []
    by_teacher = defaultdict(list)
    lessons = {m["card_id"]: m for m in proposal["moves"] if m["time_moved"]}
    for card in Card.objects.filter(pk__in=lessons).prefetch_related("lesson__teachers"):
        for t in card.lesson.teachers.all():
            if t.email:
                m = lessons[card.id]
                by_teacher[t].append(f"{m['subject_name']} ({m['classes']}): {m['from']} → {m['to']}")
    school = timetable.school
    messages = [
        EmailMessage(f"Ders programınız değişti – {school}",
                     f"Sayın {t.full_name},\n\n{school} programında kalıcı bir değişiklik yapıldı:\n\n"
                     + "\n".join(f"• {line}" for line in lines) + "\n", to=[t.email])
        for t, lines in by_teacher.items()
    ]
    return notify._send(messages)


# --- ekran -----------------------------------------------------------------------------------

def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def center_view(request, pk):
    """Çözüm merkezi ekranı: istek → öneriler (etki raporuyla) → uygula."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect, render

    from .models import Classroom, Teacher, Timetable
    from .views import _nav

    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    session_key = f"resolve-{timetable.pk}"
    data = request.POST if request.method == "POST" else request.GET
    kind = data.get("tur") if data.get("tur") in ("shift", "place", "teacher", "room", "insert") else "shift"
    card_id = _int(data.get("kart"))
    teacher_id = _int(data.get("ogretmen"))
    if card_id and not teacher_id:
        teacher_id = Card.objects.filter(pk=card_id).values_list("lesson__teachers", flat=True).first()
    form = {
        "kind": kind, "card": card_id, "teacher": teacher_id, "room": _int(data.get("derslik")),
        "day": _int(data.get("gun"), 0), "period": _int(data.get("saat"), 0),
        "periods": [int(p) for p in data.getlist("saatler") if p.isdigit()] if hasattr(data, "getlist") else [],
        "max_moves": min(10, max(1, _int(data.get("en_fazla"), 4))), "same_day": data.get("ayni_gun") == "1",
    }

    if request.method == "POST" and request.POST.get("action") == "swap":
        from . import swaps

        stored = request.session.get(session_key) or {}
        index = _int(request.POST.get("oneri"), -1)
        options = stored.get("swaps") or []
        if not 0 <= index < len(options):
            messages.error(request, "Öneri bulunamadı; yeniden hesaplayın.")
            return redirect("timetable:solution_center", pk=timetable.pk)
        option = options[index]
        closure = None
        if request.POST.get("musaitlik") == "1" and stored.get("availability"):
            _, teacher_pk, day, periods = stored["availability"]
            closure = (teacher_pk, day, periods)
        try:
            swaps.apply(timetable, option, closure)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("timetable:solution_center", pk=timetable.pk)
        request.session.pop(session_key, None)
        text = "; ".join(f"{s['subject']}: {s['teacher']} {s['class1']} ↔ {s['other']} {s['class2']}" for s in option["swaps"])
        messages.success(request, f"Kısım değişikliği yapıldı: {text}. Ders verisi değişti; programın tüm sürümlerinde geçerlidir.")
        return redirect("timetable:timetable_detail", pk=timetable.pk)

    if request.method == "POST" and request.POST.get("action") == "apply":
        stored = request.session.get(session_key) or {}
        index = _int(request.POST.get("oneri"), -1)
        proposals = stored.get("proposals") or []
        if not 0 <= index < len(proposals):
            messages.error(request, "Öneri bulunamadı; yeniden hesaplayın.")
            return redirect("timetable:solution_center", pk=timetable.pk)
        proposal = proposals[index]
        availability = None
        if request.POST.get("musaitlik") == "1" and stored.get("availability"):
            field, obj_id, day, periods = stored["availability"]
            model = Teacher if field == "teacher" else Classroom
            obj = model.objects.filter(pk=obj_id, school=school).first()
            availability = (field, obj, day, periods) if obj else None
        try:
            apply(timetable, proposal, stored["label"], request.user, availability)
        except ResolveError as exc:
            messages.error(request, str(exc))
            return redirect("timetable:solution_center", pk=timetable.pk)
        request.session.pop(session_key, None)
        messages.success(request, f"Uygulandı: {stored['label']} · {proposal['count']} ders yer değiştirdi. Geri almak için ana görünümde “Geri al”.")
        if request.POST.get("bildir") == "1":
            sent, errors = notify_moves(timetable, proposal)
            if sent:
                messages.info(request, f"{sent} öğretmene e-posta gönderildi.")
            for e in errors[:3]:
                messages.warning(request, e)
        return redirect("timetable:timetable_detail", pk=timetable.pk)

    proposals, label, error = None, "", ""
    parsed, swap_list = None, None
    if request.method == "GET" and request.GET.get("goster") == "1":  # kalite karnesinden "İyileştir" sonucu
        stored = request.session.get(session_key) or {}
        proposals, label, swap_list = stored.get("proposals") or None, stored.get("label", ""), stored.get("swaps")
    if request.method == "POST" and request.POST.get("action") == "text":
        from .resolve_text import parse

        parsed = parse(school, timetable, request.POST.get("istek", ""))
        form.update({k: v for k, v in parsed["form"].items() if v is not None})
        teacher_id = form["teacher"]
    auto = request.method == "GET" and request.GET.get("hesapla") == "1"  # bekleyenler ekranından "yer aç"
    if (request.method == "POST" and request.POST.get("action") == "solve") or (parsed and not parsed["problems"]) or auto:
        center = Center(timetable)
        req = availability = None
        try:
            req, label, availability = _build_request(center, form)
            proposals = center.proposals(req)
            if not proposals:
                error = f"En fazla {form['max_moves']} değişiklikle çakışmasız çözüm bulunamadı. Değişiklik sınırını artırıp yeniden deneyin."
        except ResolveError as exc:
            error = str(exc)
        if req is not None and req.kind == "teacher":  # kart oynatmadan: aynı dersin kısımlarını öğretmenler arasında değiştir
            from . import swaps

            swap_list = swaps.find(timetable, req.teacher_id, req.day, req.periods)
        if req is not None:
            request.session[session_key] = {"label": label, "proposals": proposals or [], "availability": availability, "swaps": swap_list}

    teachers = list(school.teachers.all())
    teacher_cards = []
    if teacher_id:
        for c in timetable.cards.filter(lesson__teachers=teacher_id, day__isnull=False).select_related("lesson__subject").prefetch_related("lesson__classes").order_by("day", "period"):
            teacher_cards.append({"id": c.id, "label": f"{_where(c.day, c.period, c.length)} · {c.lesson.subject.short or c.lesson.subject.name} · "
                                                      + ", ".join(x.short or x.name for x in c.lesson.classes.all()), "locked": c.locked})
        if not form["card"] and teacher_cards:
            form["card"] = teacher_cards[0]["id"]
    return render(request, "timetable/solution_center.html", _nav(
        school, "solution", timetable=timetable, form=form, teachers=teachers, teacher_cards=teacher_cards,
        rooms=list(school.classrooms.all()), days=list(enumerate(school.day_names)),
        periods=[(p.index, f"{p.index + 1}. saat" + (f" ({p.start_time:%H:%M})" if p.start_time else "")) for p in school.periods.all()],
        proposals=proposals, label=label, error=error, swaps=swap_list, parsed=parsed, text=request.POST.get("istek", ""), can_notify=__import__("timetable.notify", fromlist=["enabled"]).enabled(),
    ))


def _build_request(center, form):
    """Formdan istek, açıklama ve (kalıcı müsaitlik için) kayıt bilgisi."""
    school = center.school
    days = school.day_names
    kind = form["kind"]
    if kind == "insert":
        card = center.db_cards.get(form["card"])
        if card is None:
            raise ResolveError("Yerleştirilecek kart bulunamadı.")
        what = f"{card.lesson.subject.short or card.lesson.subject.name} ({', '.join(c.short or c.name for c in card.lesson.classes.all())})"
        return Request("insert", card_ids=[card.id], max_moves=form["max_moves"]), f"{what} yerleştirildi", None
    if kind in ("shift", "place"):
        card = center.db_cards.get(form["card"])
        if card is None:
            raise ResolveError("Önce öğretmeni ve taşınacak dersi seçin.")
        what = f"{card.lesson.subject.short or card.lesson.subject.name} ({', '.join(c.short or c.name for c in card.lesson.classes.all())}) {_where(card.day, card.period, card.length)}"
        if kind == "shift":
            return Request("shift", card_ids=[card.id], same_day=form["same_day"], max_moves=form["max_moves"]), f"{what} kaydırıldı", None
        target = _where(form["day"], form["period"], card.length)
        return (Request("place", card_ids=[card.id], day=form["day"], periods=[form["period"]], max_moves=form["max_moves"]),
                f"{what} → {target}", None)
    if not form["periods"]:
        raise ResolveError("Kapanacak en az bir saat seçin.")
    hours = ", ".join(str(p + 1) for p in sorted(form["periods"]))
    if kind == "teacher":
        teacher = school.teachers.filter(pk=form["teacher"]).first()
        if teacher is None:
            raise ResolveError("Öğretmen seçin.")
        return (Request("teacher", teacher_id=teacher.id, day=form["day"], periods=form["periods"], max_moves=form["max_moves"]),
                f"{teacher.full_name} {days[form['day']]} {hours}. saatlerde gelemiyor", ("teacher", teacher.id, form["day"], form["periods"]))
    room = school.classrooms.filter(pk=form["room"]).first()
    if room is None:
        raise ResolveError("Derslik seçin.")
    return (Request("room", room_id=room.id, day=form["day"], periods=form["periods"], max_moves=form["max_moves"]),
            f"{room} {days[form['day']]} {hours}. saatlerde kullanılamıyor", ("classroom", room.id, form["day"], form["periods"]))


def preview_api(request, pk, index):
    """Ana görünümde önizleme için oturumdaki önerinin hareketleri."""
    from django.http import JsonResponse

    stored = request.session.get(f"resolve-{pk}") or {}
    proposals = stored.get("proposals") or []
    if not 0 <= index < len(proposals):
        return JsonResponse({"ok": False, "message": "Öneri bulunamadı; çözüm merkezinde yeniden hesaplayın."}, status=404)
    p = proposals[index]
    from django.shortcuts import get_object_or_404

    from .models import Timetable

    violations, stats = _preview_validation(get_object_or_404(Timetable.objects.select_related("school"), pk=pk), p)
    return JsonResponse({
        "ok": True, "label": stored.get("label", ""), "index": index, "total": len(proposals), "count": p["count"],
        "new_violations": len(p["new_violations"]),
        "moves": [{"card": m["card_id"], "from": m["state_from"][:2] if m["state_from"] else None, "to": m["state_to"][:2],
                   "text": f"{m['subject']} ({m['classes']}): {m['from']} → {m['to']}"} for m in p["moves"] if m["time_moved"]],
        "violations": [v.as_dict() for v in violations], "stats": stats,
    })


def _preview_validation(timetable, proposal):
    """Öneri uygulanmış gibi doğrulama listesi ve istatistikler (ana görünüm önizlemede bunları gösterir)."""
    from .problem_cache import problem_for

    problem = problem_for(timetable)
    placements = placements_of(problem, timetable)
    keys = {card.card_id: card.key for card in problem.cards}
    for m in proposal["moves"]:
        key = keys.get(m["card_id"])
        if key is None:
            continue
        day, period, room, extra = m["state_to"]
        placements[key] = cpsat.Placement(day, period, room, tuple(extra or ()))
    return validate(problem, placements)
