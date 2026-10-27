"""Elle düzenleme: kart için hücre uygunluğu, kart taşıma ve programdan çıkarma.

aSc'deki gibi: kart tutulduğunda her hücre renklendirilir. Çakışan hücreye bırakılırsa
çakışan (kilitsiz) kartlar programdan çıkarılıp "yerleşmeyen kartlar" alanına düşer.
"""

from collections import defaultdict

from django.db import transaction

from .models import Card, Timetable
from .solver.builder import build_problem

FREE = "free"
WARN = "warn"
CONFLICT = "conflict"
BLOCKED = "blocked"


class Board:
    def __init__(self, timetable):
        self.timetable = timetable
        self.problem = build_problem(timetable.school, timetable=timetable)
        self.db_cards = {c.id: c for c in timetable.cards.all()}
        self.by_id = {pc.card_id: pc for pc in self.problem.cards}
        self.index = defaultdict(list)  # (tür, kaynak, gün, saat) -> kart kimlikleri
        for pc in self.problem.cards:
            db_card = self.db_cards[pc.card_id]
            if not db_card.is_placed:
                continue
            for cell in pc.cells(db_card.day, db_card.period):
                for kind, res in self._resources(pc, db_card.room_ids):
                    self.index[(kind, res) + cell].append(pc.card_id)

    @staticmethod
    def _resources(pc, rooms=()):
        return [("teacher", t) for t in pc.teachers] + [("atom", a) for a in pc.atoms] + [("room", r) for r in rooms]

    def _occupants(self, pc, kind, res, cells):
        found = set()
        for cell in cells:
            for other_id in self.index.get((kind, res) + cell, ()):
                if other_id != pc.card_id and pc.universes & self.by_id[other_id].universes:
                    found.add(other_id)
        return found

    RESOURCE_NAMES = {"teacher": "Öğretmen", "atom": "Sınıf", "room": "Derslik"}

    def _resource_label(self, kind, res):
        if kind == "atom":
            label = self.problem.label("class", self.problem.atom_class(res))
        else:
            label = self.problem.label(kind, res)
        return f"{self.RESOURCE_NAMES[kind]} {label}"

    def evaluate(self, card_id, day, period):
        """Kartın (gün, saat)'e konmasının sonucu: durum, gerekçeler, çakışan kartlar (kaynağıyla), derslik."""
        pc = self.by_id[card_id]
        empty = {"displace": [], "conflicts": [], "room": None, "rooms": [], "locked": []}
        if period + pc.length > self.problem.periods or day >= self.problem.days:
            return {"status": BLOCKED, "reasons": ["Gün sonunu aşıyor."], **empty}
        if (day, period) not in pc.starts:
            return {"status": BLOCKED, "reasons": ["Müsaitlik nedeniyle uygun değil (kapalı saat)."], **empty}
        cells = pc.cells(day, period)
        conflicts = defaultdict(set)  # kart → çakıştığı kaynaklar
        for kind, res in self._resources(pc):
            for cid in self._occupants(pc, kind, res, cells):
                conflicts[cid].add(self._resource_label(kind, res))

        rooms = []
        if pc.room_options:
            # Önce kartın şu anki derslikleri, sonra boş olanlar; yetmezse dolu derslikteki kartla çakışır.
            current = self.db_cards[card_id].room_ids
            ordered = sorted(pc.room_options, key=lambda r: r not in current)
            needed = max(1, min(pc.rooms_needed, len(ordered)))
            free = [
                r for r in ordered
                if len(self._occupants(pc, "room", r, cells)) < self.problem.room_slots.get(r, 1)
                and not any(c in self.problem.room_blocked.get(r, ()) for c in cells)
            ]
            rooms = free[:needed]
            for option in ordered:
                if len(rooms) >= needed:
                    break
                if option not in rooms:
                    rooms.append(option)
                    for cid in self._occupants(pc, "room", option, cells):
                        conflicts[cid].add(self._resource_label("room", option))
        room = rooms[0] if rooms else None

        warnings = []
        same_day = sum(
            1
            for other in self.db_cards.values()
            if other.id != card_id and other.lesson_id == pc.lesson_id and other.day == day
        )
        if same_day >= self.problem.lesson_max_per_day.get(pc.lesson_id, 1):
            warnings.append("Aynı ders bu gün zaten var.")
        if any(cell in pc.maybe_slots for cell in cells):
            warnings.append("Koşullu (?) hücre.")

        details = [
            {
                "card": cid,
                "lesson": self.problem.label("lesson", self.db_cards[cid].lesson_id),
                "resources": sorted(res),
                "locked": self.db_cards[cid].locked,
                "where": [self.db_cards[cid].day, self.db_cards[cid].period, self.db_cards[cid].length],
            }
            for cid, res in sorted(conflicts.items())
        ]
        reasons = [f"{', '.join(d['resources'])}: {d['lesson']}" + (" (kilitli)" if d["locked"] else "") for d in details]
        status = CONFLICT if conflicts else WARN if warnings else FREE
        return {
            "status": status,
            "reasons": reasons + warnings,
            "displace": sorted(conflicts),
            "conflicts": details,
            "locked": [d["card"] for d in details if d["locked"]],
            "room": room,
            "rooms": rooms,
        }

    def room_choices(self, card_id):
        """Kartın olası derslikleri ve o saatteki durumları (aSc 13.7: ✓ bu derslikte, ✕ dolu)."""
        pc = self.by_id[card_id]
        db_card = self.db_cards[card_id]
        result = []
        for r in pc.room_options or [r for r in self.problem.labels.get("room", {})]:
            occupied = []
            if db_card.is_placed:
                cells = pc.cells(db_card.day, db_card.period)
                occupied = [self.problem.label("lesson", self.db_cards[c].lesson_id) for c in self._occupants(pc, "room", r, cells)]
                if len(occupied) < self.problem.room_slots.get(r, 1):
                    occupied = []
            result.append({"id": r, "name": self.problem.label("room", r), "current": r in db_card.room_ids, "occupied": occupied})
        return result

    def options(self, card_id):
        pc = self.by_id[card_id]
        result = []
        for day in range(self.problem.days):
            for period in range(self.problem.periods - pc.length + 1):
                info = self.evaluate(card_id, day, period)
                result.append({"day": day, "period": period, "status": info["status"], "reasons": info["reasons"]})
        return result


# --- geri al / yinele ---------------------------------------------------------------------------

HISTORY_LIMIT = 50


def _state(card):
    return [card.id, card.day, card.period, card.classroom_id, list(card.extra_rooms or []), card.locked]


def snapshot(cards):
    return [_state(c) for c in cards]


def record(timetable, label, before):
    """Değişiklikten önceki kart durumlarını geçmişe ekler; yinele yığını temizlenir."""
    if not before:
        return
    history = (list(timetable.history or []) + [{"label": label, "cards": before}])[-HISTORY_LIMIT:]
    Timetable.objects.filter(pk=timetable.pk).update(history=history, redo_stack=[])
    timetable.history, timetable.redo_stack = history, []


def _apply(timetable, states):
    cards = {c.id: c for c in timetable.cards.filter(pk__in=[s[0] for s in states])}
    current = snapshot(cards[s[0]] for s in states if s[0] in cards)
    for card_id, day, period, room, extra, locked in states:
        card = cards.get(card_id)
        if card is None:
            continue
        card.day, card.period, card.classroom_id, card.extra_rooms, card.locked = day, period, room, extra, locked
    Card.objects.bulk_update(cards.values(), ["day", "period", "classroom", "extra_rooms", "locked"])
    return current


def _step(timetable, source, target, verb):
    with transaction.atomic():
        timetable = Timetable.objects.select_for_update().get(pk=timetable.pk)
        stack = list(getattr(timetable, source) or [])
        if not stack:
            return {"ok": False, "message": f"{verb.capitalize()} için işlem yok."}
        step = stack.pop()
        current = _apply(timetable, step["cards"])
        other = (list(getattr(timetable, target) or []) + [{"label": step["label"], "cards": current}])[-HISTORY_LIMIT:]
        Timetable.objects.filter(pk=timetable.pk).update(**{source: stack, target: other})
    return {"ok": True, "message": f"{verb.capitalize()}: {step['label']}"}


def undo(timetable):
    return _step(timetable, "history", "redo_stack", "geri alındı")


def redo(timetable):
    return _step(timetable, "redo_stack", "history", "yinelendi")


def history_info(timetable):
    history, redo_stack = timetable.history or [], timetable.redo_stack or []
    return {
        "undo": history[-1]["label"] if history else None,
        "redo": redo_stack[-1]["label"] if redo_stack else None,
    }


# --- kart işlemleri ---------------------------------------------------------------------------


def move_card(card, day, period, mode="displace"):
    """Kartı taşır. mode: "displace" çakışan kartları bekleyenlere alır, "ignore" çakışmaya rağmen
    yerleştirir, "swap" tek çakışan kartla yer değiştirir, "ask" çakışma varsa hiçbir şey yapmadan
    çakışmaları döndürür (kullanıcıya sorulur)."""
    board = Board(card.timetable)
    info = board.evaluate(card.id, day, period)
    if info["status"] == BLOCKED:
        return {"ok": False, "message": " ".join(info["reasons"])}
    conflicts = info["conflicts"]
    swap_with = None
    if conflicts and card.is_placed and len(conflicts) == 1:
        other = board.db_cards[conflicts[0]["card"]]
        if other.length == card.length and not other.locked:
            swap_with = other
    if conflicts and mode == "ask":
        return {
            "ok": False, "ask": True, "conflicts": conflicts, "can_displace": not info["locked"],
            "can_swap": swap_with is not None, "message": "Çakışma var.",
        }
    if mode == "displace" and info["locked"]:
        return {"ok": False, "message": "Kilitli kartla çakışıyor; önce kilidi açın ya da “görmezden gel” seçin."}
    label = board.problem.label("lesson", card.lesson_id)
    if mode == "swap" and swap_with is not None:
        record(card.timetable, f"{label} yer değiştirdi", snapshot([card, swap_with]))
        old = (card.day, card.period, card.classroom_id, list(card.extra_rooms or []))
        swap_with.day, swap_with.period, swap_with.classroom_id, swap_with.extra_rooms = old
        card.day, card.period, card.classroom_id, card.extra_rooms = day, period, info["room"], info["rooms"][1:]
        Card.objects.bulk_update([card, swap_with], ["day", "period", "classroom", "extra_rooms"])
        return {"ok": True, "displaced": [], "message": f"Kartlar yer değiştirdi ({board.problem.label('lesson', swap_with.lesson_id)})."}
    displace = info["displace"] if mode == "displace" else []
    affected = [card] + list(Card.objects.filter(pk__in=displace))
    record(card.timetable, f"{label} taşındı", snapshot(affected))
    Card.objects.filter(pk__in=displace).update(day=None, period=None, classroom=None, extra_rooms=[])
    card.day, card.period, card.classroom_id, card.extra_rooms = day, period, info["room"], info["rooms"][1:]
    card.save(update_fields=["day", "period", "classroom", "extra_rooms"])
    message = _move_message(info) if mode == "displace" else (
        f"Kart çakışmayla yerleştirildi ({len(conflicts)} kart). Doğrulamada görünür." if conflicts else "Kart taşındı."
    )
    return {"ok": True, "displaced": displace, "message": message}


def set_room(card, room_id):
    """Kartın dersliğini değiştirir (aSc 13.7); None dersliği boşaltır."""
    if not card.is_placed:
        return {"ok": False, "message": "Önce kartı yerleştirin."}
    if room_id is not None and not card.timetable.school.classrooms.filter(pk=room_id).exists():
        return {"ok": False, "message": "Derslik bulunamadı."}
    record(card.timetable, "derslik değişti", snapshot([card]))
    card.classroom_id = room_id
    card.extra_rooms = [r for r in card.extra_rooms or [] if r != room_id] if room_id else []
    card.save(update_fields=["classroom", "extra_rooms"])
    return {"ok": True, "message": "Derslik değiştirildi." if room_id else "Derslik boşaltıldı."}


def row_cards(timetable, kind, row_id):
    """Ana görünümdeki bir satırın (sınıf/öğretmen/derslik) yerleşmiş kartları."""
    cards = timetable.cards.filter(day__isnull=False)
    if kind == "sinif":
        return list(cards.filter(lesson__classes__id=row_id).distinct())
    if kind == "ogretmen":
        return list(cards.filter(lesson__teachers__id=row_id).distinct())
    return [c for c in cards if row_id in c.room_ids]


def row_action(timetable, kind, row_id, action):
    cards = row_cards(timetable, kind, row_id)
    if action == "clear":
        changed = [c for c in cards if not c.locked]
        record(timetable, "satır temizlendi", snapshot(changed))
        for c in changed:
            c.day = c.period = c.classroom_id = None
            c.extra_rooms = []
        _save(changed, ["day", "period", "classroom", "extra_rooms"])
        return {"ok": True, "message": f"{len(changed)} kart bekleyenlere alındı."}
    if action in ("lock", "unlock"):
        lock = action == "lock"
        changed = [c for c in cards if c.locked != lock]
        record(timetable, "satır kilitlendi" if lock else "satır kilidi açıldı", snapshot(changed))
        for c in changed:
            c.locked = lock
        _save(changed, ["locked"])
        return {"ok": True, "message": f"{len(changed)} kart {'kilitlendi' if lock else 'kilidi açıldı'}."}
    return {"ok": False, "message": "Bilinmeyen işlem."}


def cell_candidates(timetable, kind, row_id, day, period):
    """Boş hücreye sağ tıklanınca: o satırın bekleyen kartlarından buraya konabilenler (aSc 13.5)."""
    board = Board(timetable)
    unplaced = [c for c in board.db_cards.values() if not c.is_placed]
    if kind == "sinif":
        mine = set(timetable.cards.filter(day__isnull=True, lesson__classes__id=row_id).values_list("id", flat=True))
    elif kind == "ogretmen":
        mine = set(timetable.cards.filter(day__isnull=True, lesson__teachers__id=row_id).values_list("id", flat=True))
    else:
        mine = {c.id for c in unplaced if row_id in board.by_id[c.id].room_options}
    result = []
    for card in unplaced:
        if card.id not in mine:
            continue
        info = board.evaluate(card.id, day, period)
        if info["status"] != BLOCKED:
            result.append({"card": card.id, "lesson": board.problem.label("lesson", card.lesson_id), "length": card.length,
                           "status": info["status"], "reasons": info["reasons"]})
    result.sort(key=lambda r: (r["status"] != FREE, r["lesson"]))
    return result


def _move_message(info):
    if info["displace"]:
        return f"Kart taşındı; {len(info['displace'])} çakışan kart bekleyenlere alındı."
    return "Kart taşındı."


def unplace_card(card):
    if card.locked:
        return {"ok": False, "message": "Kilitli kart programdan çıkarılamaz."}
    record(card.timetable, f"{card.lesson.subject} kartı çıkarıldı", snapshot([card]))
    card.day = card.period = card.classroom = None
    card.extra_rooms = []
    card.save(update_fields=["day", "period", "classroom", "extra_rooms"])
    return {"ok": True, "message": "Kart bekleyenlere alındı."}


def toggle_lock(card):
    record(card.timetable, "kilit " + ("açıldı" if card.locked else "kondu"), snapshot([card]))
    card.locked = not card.locked
    card.save(update_fields=["locked"])
    return {"ok": True, "locked": card.locked, "message": "Kart kilitlendi." if card.locked else "Kilit açıldı."}


# --- toplu işlemler (aSc "Diğer" menüsü) ------------------------------------------------------


def _save(cards, fields):
    if not cards:
        return 0
    Card.objects.bulk_update(cards, fields)
    return len(cards)


def bulk_action(timetable, action, a=None, b=None):
    """Toplu işlem; dönüş {"ok", "message"}. Her işlem tek adımda geri alınabilir."""
    school = timetable.school
    cards = list(timetable.cards.all())
    placed = [c for c in cards if c.is_placed]
    days, periods = school.days_per_week, school.periods.count()

    if action in ("swap_days", "swap_periods"):
        limit = days if action == "swap_days" else periods
        try:
            a, b = int(a), int(b)
        except (TypeError, ValueError):
            return {"ok": False, "message": "İki değer seçin."}
        if a == b or not (0 <= a < limit and 0 <= b < limit):
            return {"ok": False, "message": "Farklı iki geçerli değer seçin."}
    if action == "swap_days":
        changed = [c for c in placed if c.day in (a, b)]
        record(timetable, f"{school.day_names[a]} ↔ {school.day_names[b]}", snapshot(changed))
        for c in changed:
            c.day = b if c.day == a else a
        n = _save(changed, ["day"])
        return {"ok": True, "message": f"{school.day_names[a]} ve {school.day_names[b]} yer değiştirdi ({n} kart)."}
    if action == "swap_periods":
        touches = lambda c, p: c.period <= p < c.period + c.length  # noqa: E731
        blocks = [c for c in placed if c.length > 1 and (touches(c, a) or touches(c, b))]
        changed = [c for c in placed if c.length == 1 and c.period in (a, b)]
        record(timetable, f"{a + 1}. saat ↔ {b + 1}. saat", snapshot(changed))
        for c in changed:
            c.period = b if c.period == a else a
        n = _save(changed, ["period"])
        note = f" {len(blocks)} blok kart yerinde bırakıldı." if blocks else ""
        return {"ok": True, "message": f"{a + 1}. ve {b + 1}. saatler yer değiştirdi ({n} kart).{note}"}
    if action in ("lock_all", "unlock_all"):
        lock = action == "lock_all"
        changed = [c for c in placed if c.locked != lock]
        record(timetable, "tümü kilitlendi" if lock else "tüm kilitler açıldı", snapshot(changed))
        for c in changed:
            c.locked = lock
        n = _save(changed, ["locked"])
        return {"ok": True, "message": f"{n} kart {'kilitlendi' if lock else 'kilidi açıldı'}."}
    if action == "unplace_unlocked":
        changed = [c for c in placed if not c.locked]
        record(timetable, "kilitsiz kartlar çıkarıldı", snapshot(changed))
        for c in changed:
            c.day = c.period = c.classroom_id = None
            c.extra_rooms = []
        n = _save(changed, ["day", "period", "classroom", "extra_rooms"])
        return {"ok": True, "message": f"{n} kilitsiz kart bekleyenlere alındı. “Bekleyenleri yerleştir” ile yeniden dağıtabilirsiniz."}
    return {"ok": False, "message": "Bilinmeyen işlem."}
