"""Elle düzenleme: kart için hücre uygunluğu, kart taşıma ve programdan çıkarma.

aSc'deki gibi: kart tutulduğunda her hücre renklendirilir. Çakışan hücreye bırakılırsa
çakışan (kilitsiz) kartlar programdan çıkarılıp "yerleşmeyen kartlar" alanına düşer.
"""

from collections import defaultdict

from .models import Card
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
                if not self._occupants(pc, "room", r, cells)
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


def move_card(card, day, period):
    board = Board(card.timetable)
    info = board.evaluate(card.id, day, period)
    if info["status"] == BLOCKED:
        return {"ok": False, "message": " ".join(info["reasons"])}
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
    card.day = card.period = card.classroom = None
    card.extra_rooms = []
    card.save(update_fields=["day", "period", "classroom", "extra_rooms"])
    return {"ok": True, "message": "Kart bekleyenlere alındı."}
