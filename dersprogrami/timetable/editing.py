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

    def evaluate(self, card_id, day, period):
        """Kartın (gün, saat)'e konmasının sonucu: durum, gerekçeler, çıkarılacak kartlar, derslik."""
        pc = self.by_id[card_id]
        if period + pc.length > self.problem.periods or day >= self.problem.days:
            return {"status": BLOCKED, "reasons": ["Gün sonunu aşıyor."], "displace": [], "room": None}
        if (day, period) not in pc.starts:
            return {"status": BLOCKED, "reasons": ["Müsaitlik nedeniyle uygun değil."], "displace": [], "room": None}
        cells = pc.cells(day, period)
        conflicts = set()
        for kind, res in self._resources(pc):
            conflicts |= self._occupants(pc, kind, res, cells)

        rooms = []
        if pc.room_options:
            # Önce kartın şu anki derslikleri, sonra boş olanlar; yetmezse dolu derslikteki kart çıkarılır.
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
                    conflicts |= self._occupants(pc, "room", option, cells)
        room = rooms[0] if rooms else None

        reasons, warnings = [], []
        locked = [cid for cid in conflicts if self.db_cards[cid].locked]
        for cid in sorted(conflicts):
            reasons.append(self.problem.label("lesson", self.db_cards[cid].lesson_id))
        if locked:
            return {"status": BLOCKED, "reasons": ["Kilitli kartla çakışıyor."] + reasons, "displace": [], "room": room, "rooms": rooms}

        same_day = sum(
            1
            for other in self.db_cards.values()
            if other.id != card_id and other.lesson_id == pc.lesson_id and other.day == day
        )
        if same_day >= self.problem.lesson_max_per_day.get(pc.lesson_id, 1):
            warnings.append("Aynı ders bu gün zaten var.")
        if any(cell in pc.maybe_slots for cell in cells):
            warnings.append("Koşullu (?) hücre.")

        if conflicts:
            status = CONFLICT
        elif warnings:
            status = WARN
        else:
            status = FREE
        return {"status": status, "reasons": reasons + warnings, "displace": sorted(conflicts), "room": room, "rooms": rooms}

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


def move_card(card, day, period):
    board = Board(card.timetable)
    info = board.evaluate(card.id, day, period)
    if info["status"] == BLOCKED:
        return {"ok": False, "message": " ".join(info["reasons"])}
    affected = [card] + list(Card.objects.filter(pk__in=info["displace"]))
    record(card.timetable, f"{board.problem.label('lesson', card.lesson_id)} taşındı", snapshot(affected))
    displaced = Card.objects.filter(pk__in=info["displace"])
    displaced.update(day=None, period=None, classroom=None, extra_rooms=[])
    card.day, card.period, card.classroom_id, card.extra_rooms = day, period, info["room"], info["rooms"][1:]
    card.save(update_fields=["day", "period", "classroom", "extra_rooms"])
    return {"ok": True, "displaced": info["displace"], "message": _move_message(info)}


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
