"""Ceza dökümü: "Bu ceza neden var?"

Yerleşmiş bir programın (kartların şu anki yerleri) yumuşak cezasını kalemlerine ayırır: hangi kural, hangi
öğretmen / sınıf / ilişki, hangi hücreler, ağırlık × miktar. Tanım çözücünün amaç fonksiyonuyla aynıdır;
ağırlıklar cpsat.py'den alınır, burada sayı kopyalanmaz.

İki katman vardır:

1. Saf Python hesap (çözücü çalışmaz): öğretmen ve sınıf boşlukları, güne geç başlama, öğretmenin okula geldiği
   gün, koşullu (?) hücre, yerleşmeyen kart, öğretmen havuzunda değişen öğretmen. Ayrıntılar (hücreler,
   kartlar) ve "Ne yapılabilir?" ipuçları bu katmandan gelir.
2. Kart ilişkileri ve esnetilen kesin kurallar için çözücünün kendi modeli kurulur, kartlar şu anki yerlerine
   sabitlenir ve ceza değişkenleri okunur (ilişki koşulları 70'e yakındır; ayrı bir kopyasını yazmak yerine aynı
   kod kullanılır, böylece tanım birebir aynı kalır). Kartlar sabit olduğundan çözüm ön işlemede biter. Model
   yalnızca gerektiğinde kurulur: önemi kesin olmayan ilişki varsa yalnızca ilişkiler (hızlı), aşılmış bir kesin
   kural varsa tam model (gerçek veride ~5 sn; sonuç aynı yerleşim için bellekte tutulur). Tam modelde saf Python
   kalemleri modelin değerleriyle de karşılaştırılır ("mismatch").

Programın problemi üretimden sonra değişmiş olabilir (veri düzenlendi, kart elle taşındı); döküm her zaman güncel
veriyle ve kartların bugünkü yerleriyle hesaplanır, bu yüzden üretimde bildirilen puandan farklı olabilir.

Çözücünün raporladığı amaç (Timetable.objective) bu dökümün toplamına eşittir; tek fark, süre sınırıyla biten
("feasible") bir çözümde çözücünün bir ceza değişkenini gerekenden büyük bırakabilmesidir (değişkenler yalnızca
alttan sınırlıdır): döküm her zaman yerleşimin gerçek (en küçük) cezasını verir.

Yeniden üretilmeyen terimler: Çözüm merkezinin "yerinden oynayan kart / derslik" (moved, moved_room) cezaları;
bunlar bir başlangıç programına göre tanımlıdır ve üretimin amacında yoktur.
"""

import copy
import threading
import time
from collections import defaultdict
from dataclasses import replace
from urllib.parse import quote

from .solver import cpsat
from .solver.cpsat import (
    PENALTY_LABELS,
    W_CLASS_GAP,
    W_CLASS_LATE_START,
    W_MAYBE,
    W_RELAXED,
    W_TEACHER_CHANGED,
    W_TEACHER_GAP,
    W_UNPLACED,
)

# Dökümde gösterilen sıra ve adlar (çözücünün kategori adlarıyla aynı anahtarlar)
KIND_ORDER = ("unplaced", "relaxed", "class_gap", "class_late", "teacher_gap", "teacher_day", "relationship", "maybe",
              "teacher_changed")
KIND_LABELS = {**PENALTY_LABELS, "relaxed": "Esnetilen kesin kural"}


def _share(part, total):
    """Yüzde: 1'in altında bir ondalıkla (0 görünüp yanıltmasın)."""
    if not total:
        return 0
    value = 100 * part / total
    if 0 < value < 0.1:
        return "<0,1"
    return round(value, 1) if value < 1 else round(value)


def _runs(periods):
    """Ardışık saat kümelerini "3.–4. saat" gibi yazmak için [(ilk, son), ...]."""
    out = []
    for p in sorted(periods):
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return out


def _hours_text(periods):
    parts = [f"{a + 1}." if a == b else f"{a + 1}.–{b + 1}." for a, b in _runs(periods)]
    return ", ".join(parts) + " saat"


def _gap_slots(periods):
    """Gün içindeki boşluk saatleri: ilk ve son dersin arasında kalan boş saatler (çözücünün tanımı)."""
    if not periods:
        return []
    return [s for s in range(min(periods) + 1, max(periods)) if s not in periods]


class _Context:
    """Problemi ve yerleşimi bir kez dolaşıp dökümün ihtiyaç duyduğu dizinleri tutar."""

    def __init__(self, problem, placements, choice, day_names):
        self.problem = problem
        self.placements = placements
        self.choice = choice
        self.day_names = day_names or [f"{d + 1}. gün" for d in range(problem.days)]
        self.teacher_cards = defaultdict(list)  # öğretmen → kart anahtarları (havuzdakiler seçilen öğretmende)
        self.atom_cards = defaultdict(list)
        self._occ = defaultdict(set)  # (kaynak, hücre) → o hücreyi kaplayan kartlar
        for card in problem.cards:
            for t in self.teachers_of(card):
                self.teacher_cards[t].append(card.key)
            for a in card.atoms:
                self.atom_cards[a].append(card.key)
            place = placements.get(card.key)
            if place is not None:
                for cell in card.cells(place.day, place.period):
                    for res in self.resources(card):
                        self._occ[(res, cell)].add(card.key)

    def resources(self, card):
        return [("teacher", t) for t in self.teachers_of(card)] + [("atom", a) for a in card.atoms] + [
            ("students", s) for s in card.students]

    def occupied(self, res, cell, except_key=None):
        return bool(self._occ.get((res, cell), set()) - {except_key})

    def teachers_of(self, card):
        if card.teachers:
            return card.teachers
        chosen = self.choice.get(card.lesson_id)
        return (chosen,) if chosen is not None else ()

    def day(self, d):
        return self.day_names[d] if d < len(self.day_names) else f"{d + 1}. gün"

    def busy(self, keys):
        """{gün: {saat: [kart, ...]}} — kümenin yerleşmiş kartlarının kapladığı hücreler."""
        out = defaultdict(lambda: defaultdict(list))
        for key in keys:
            place = self.placements.get(key)
            if place is None:
                continue
            for d, p in self.problem.cards[key].cells(place.day, place.period):
                out[d][p].append(key)
        return out

    def can_cover(self, key, cell):
        """Kart bu hücreyi kaplayacak biçimde başlayabilir mi (müsaitlik ve süreye göre)?"""
        card = self.problem.cards[key]
        d, s = cell
        return any((d, p) in card.starts or card.fixed == (d, p) for p in range(s - card.length + 1, s + 1) if p >= 0)

    def blockers(self, keys, cell):
        """Hücreyi kümenin hiçbir kartı kaplayamıyorsa müsaitlikle kapatan varlıkların adları."""
        labels = self.problem.labels.get("entity", {})
        found = []
        for key in keys:
            card = self.problem.cards[key]
            d, s = cell
            for p in range(max(0, s - card.length + 1), s + 1):
                for entity in card.blocked.get((d, p), ()):
                    name = labels.get(entity, str(entity))
                    if name not in found:
                        found.append(name)
        return found

    def label(self, kind, key):
        return self.problem.label(kind, key)


# Miktarın birimi ("2 boşluk × 10")
UNITS = {"unplaced": "kart", "relaxed": "aşım", "relationship": "ihlal", "class_gap": "boşluk", "class_late": "gün",
         "teacher_gap": "boşluk", "teacher_day": "gün", "maybe": "saat", "teacher_changed": "değişim"}


def _item(kind, owner, owner_id, name, weight=None):
    return {"kind": kind, "label": KIND_LABELS.get(kind, kind), "unit": UNITS.get(kind, ""), "owner": owner,
            "owner_id": owner_id, "name": name,
            "weight": weight, "amount": 0, "penalty": 0, "details": [], "hints": []}


def _detail(item, text, amount, weight, cells=(), cards=()):
    item["details"].append({"text": text, "amount": amount, "weight": weight, "penalty": amount * weight,
                            "cells": list(cells), "cards": list(cards)})
    item["amount"] += amount
    item["penalty"] += amount * weight


# --- saf Python terimleri ----------------------------------------------------------------------


def _teacher_terms(ctx):
    items = []
    problem = ctx.problem
    for teacher_id, keys in ctx.teacher_cards.items():
        weights = problem.teacher_weights.get(teacher_id)
        w_gap = weights[0] if weights else W_TEACHER_GAP
        w_day = weights[1] if weights else 0
        name = ctx.label("teacher", teacher_id)
        busy = ctx.busy(keys)
        gap_item = _item("teacher_gap", "teacher", teacher_id, name, w_gap)
        forced = []  # müsaitlik yüzünden zorunlu boşluklar
        for d in sorted(busy):
            periods = set(busy[d])
            slots = _gap_slots(periods)
            if slots and w_gap:
                _detail(gap_item, f"{ctx.day(d)}: {_hours_text(slots)} boş", len(slots), w_gap,
                        cells=[(d, s) for s in slots], cards=sorted({k for ks in busy[d].values() for k in ks}))
                for s in slots:
                    if not any(ctx.can_cover(k, (d, s)) for k in keys):
                        forced.append(((d, s), ctx.blockers(keys, (d, s))))
        if gap_item["amount"]:
            _teacher_gap_hints(ctx, gap_item, teacher_id, keys, busy, forced)
            items.append(gap_item)
        if w_day:
            day_item = _item("teacher_day", "teacher", teacher_id, name, w_day)
            for d in sorted(busy):
                _detail(day_item, f"{ctx.day(d)}: okula geliyor ({len(busy[d])} saat)", 1, w_day, cards=sorted({k for ks in busy[d].values() for k in ks}))
            if day_item["amount"]:
                _teacher_day_hints(ctx, day_item, teacher_id, keys)
                items.append(day_item)
    return items


def _possible_days(ctx, keys):
    days = set()
    for key in keys:
        card = ctx.problem.cards[key]
        days |= {d for d, _ in card.starts}
        if card.fixed is not None:
            days.add(card.fixed[0])
    return days


def _teacher_gap_hints(ctx, item, teacher_id, keys, busy, forced):
    problem = ctx.problem
    hints = item["hints"]
    for (d, s), names in forced:
        who = f" ({', '.join(names)})" if names else ""
        hints.append(f"{ctx.day(d)} {s + 1}. saat bu öğretmenin hiçbir dersine açık değil{who}: bu boşluk müsaitlikten "
                     f"kaynaklanıyor; o saati açmak {item['weight']} puanlık cezayı kaldırabilir.")
    hours = sum(problem.cards[k].length for k in keys if k in ctx.placements)
    days = _possible_days(ctx, keys)
    used = len([d for d in busy if busy[d]])
    if days and len(days) < problem.days:
        names = ", ".join(ctx.day(d) for d in sorted(days))
        hints.append(f"Müsaitliğe göre dersleri yalnızca {len(days)} güne konabiliyor ({names}); haftalık {hours} saat "
                     f"bu günlere sıkıştığı için boşluk kaçınılmaz olabilir. Başka bir günü açmak bu cezayı azaltabilir.")
    limits = problem.teacher_limits.get(teacher_id)
    if limits and limits.max_days_per_week is not None and used >= limits.max_days_per_week:
        hints.append(f"Haftada en fazla {limits.max_days_per_week} gün sınırı var ve öğretmen {used} gün geliyor; "
                     f"{hours} saat bu kadar güne sığdırıldığı için boşluk oluşuyor. Sınırı artırmak boşluğu azaltabilir.")
    if limits and limits.max_consecutive is not None:
        n = limits.max_consecutive
        for detail in item["details"]:
            for d, s in detail["cells"]:
                before = [p for p in range(s - n, s) if p >= 0 and p in busy[d]]
                after = [p for p in range(s + 1, s + n + 1) if p in busy[d]]
                if len(before) == n or len(after) == n:
                    hints.append(f"{ctx.day(d)} {s + 1}. saat: hemen yanında art arda {n} ders var; “art arda en fazla {n} "
                                 "ders” sınırı bu boşluğu zorunlu kılıyor.")
    _move_hints(ctx, item, keys)


def _move_hints(ctx, item, keys):
    """Boşluğu kapatabilecek tek kart kaydırmaları: kart o saate başlayabiliyor ve öğretmeni ile sınıfı orada boş."""
    best = {}  # kart → (boşluk sonrası, boşluk önce, yeni saat): kart başına en iyi kaydırma
    for detail in item["details"]:
        for key in detail["cards"]:
            now = _gaps_after_move(ctx, keys, key, None)
            for cell in detail["cells"]:
                for p in _free_moves(ctx, key, cell):
                    after = _gaps_after_move(ctx, keys, key, p)
                    if after < now and (key not in best or after < best[key][0]):
                        best[key] = (after, now, p)
    for key, (after, now, p) in sorted(best.items(), key=lambda kv: kv[1][0] - kv[1][1])[:3]:
        card = ctx.problem.cards[key]
        place = ctx.placements[key]
        text = (f"{ctx.day(place.day)}: {ctx.label('lesson', card.lesson_id)} {place.period + 1}. saatten {p + 1}. saate "
                f"kayarsa bu günün boşluğu {now} → {after} olur; kartın öğretmeni ve sınıfı o saatte boş. Başka bir yerde "
                "etkisini (derslik dahil) Çözüm merkezindeki “Dersi şu saate al” önerisi gösterir.")
        if text not in item["hints"]:
            item["hints"].append(text)


def _gaps_after_move(ctx, keys, key, period):
    """Kart (aynı gün içinde) period saatine kayarsa sahibinin o günkü boşluk sayısı (None: şu anki hali)."""
    place = ctx.placements[key]
    periods = set()
    for k in keys:
        other = ctx.placements.get(k)
        if other is None or other.day != place.day:
            continue
        start = period if k == key and period is not None else other.period
        periods |= {p for _, p in ctx.problem.cards[k].cells(other.day, start)}
    return len(_gap_slots(periods))


def _free_moves(ctx, key, cell):
    """Kartın aynı gün içinde hücreyi kaplayacak, öğretmeni ve öğrencileri boş olan başlangıç saatleri."""
    card = ctx.problem.cards[key]
    place = ctx.placements.get(key)
    if place is None or card.fixed is not None:
        return []
    d, s = cell
    if place.day != d:
        return []
    current = set(card.cells(place.day, place.period))
    out = []
    for p in range(max(0, s - card.length + 1), s + 1):
        if (d, p) not in card.starts or p == place.period:
            continue
        new = [c for c in card.cells(d, p) if c not in current]
        if all(not ctx.occupied(r, c, key) for c in new for r in ctx.resources(card)):
            out.append(p)
    return out


def _teacher_day_hints(ctx, item, teacher_id, keys):
    hours = sum(ctx.problem.cards[k].length for k in keys if k in ctx.placements)
    limits = ctx.problem.teacher_limits.get(teacher_id)
    per_day = limits.max_periods_per_day if limits and limits.max_periods_per_day else ctx.problem.periods
    need = -(-hours // max(1, per_day))
    if item["amount"] > need:
        item["hints"].append(f"Haftalık {hours} saat en az {need} güne sığar; şu an {item['amount']} gün geliyor.")


def _class_terms(ctx):
    problem = ctx.problem
    by_class = {}
    atom_count = defaultdict(int)
    for atom_id in ctx.atom_cards:
        atom_count[problem.atom_class(atom_id)] += 1
    for atom_id, keys in ctx.atom_cards.items():
        class_id = problem.atom_class(atom_id)
        name = ctx.label("class", class_id)
        part = f" ({problem.labels.get('atom', {}).get(atom_id, atom_id)})" if atom_count[class_id] > 1 else ""
        busy = ctx.busy(keys)
        for d in sorted(busy):
            periods = set(busy[d])
            slots = _gap_slots(periods)
            cards = sorted({k for ks in busy[d].values() for k in ks})
            if slots:
                item = by_class.setdefault(("class_gap", class_id), _item("class_gap", "class", class_id, name, W_CLASS_GAP))
                _detail(item, f"{ctx.day(d)}{part}: {_hours_text(slots)} boş", len(slots), W_CLASS_GAP,
                        cells=[(d, s) for s in slots], cards=cards)
                for s in slots:
                    _cell_hint(ctx, item, keys, (d, s))
                # Bu atomun bu günkü boşluğu için kaydırma ipucu (ipuçları sınıfın kalemine eklenir)
                probe = {"details": item["details"][-1:], "hints": item["hints"]}
                _move_hints(ctx, probe, keys)
            if problem.periods > 1 and periods and min(periods) > 0:
                item = by_class.setdefault(("class_late", class_id), _item("class_late", "class", class_id, name, W_CLASS_LATE_START))
                first = min(periods)
                _detail(item, f"{ctx.day(d)}{part}: ilk ders {first + 1}. saatte (1. saat boş)", 1, W_CLASS_LATE_START,
                        cells=[(d, 0)], cards=cards)
                _cell_hint(ctx, item, keys, (d, 0))
    for (_, class_id), item in by_class.items():
        n = atom_count[class_id]
        if n > 1:
            item["hints"].insert(0, f"Sınıf bölünmeler yüzünden {n} öğrenci grubuna ayrılıyor; çözücü boşluğu ve geç "
                                    f"başlamayı her grup için ayrı sayar, ortak bir boş saat {n} kez cezalanır. "
                                    "Derslerde kullanılmayan bir bölünme varsa kaldırmak cezayı küçültür.")
    return list(by_class.values())


def _cell_hint(ctx, item, keys, cell):
    """Sınıfın boş hücresi: kartlardan biri oraya konabilir mi, konamıyorsa neden?"""
    d, s = cell
    candidates = [k for k in keys if ctx.can_cover(k, cell)]
    where = f"{ctx.day(d)} {s + 1}. saat"
    if not candidates:
        names = ctx.blockers(keys, cell)
        who = f" ({', '.join(names)})" if names else ""
        text = (f"{where} bu sınıfın hiçbir dersine açık değil{who}: ceza müsaitlikten kaynaklanıyor; o saati açmak bu "
                f"cezayı kaldırabilir.")
    else:
        # Oraya konabilecek derslerin öğretmenleri o saatte başka derste mi?
        busy_teachers = set()
        free = False
        for key in candidates:
            teachers = ctx.teachers_of(ctx.problem.cards[key])
            taken = [t for t in teachers if any(k != key and _covers(ctx, k, cell) for k in ctx.teacher_cards[t])]
            if taken:
                busy_teachers.update(taken)
            else:
                free = True
        if free or not busy_teachers:
            return
        names = ", ".join(sorted(ctx.label("teacher", t) for t in busy_teachers))
        text = (f"{where}: bu saate konabilecek derslerin öğretmenleri o saatte başka derste ({names}). "
                f"Bu öğretmenlerin o saatteki dersi kayarsa boşluk kapanabilir.")
    if text not in item["hints"]:
        item["hints"].append(text)


def _covers(ctx, key, cell):
    place = ctx.placements.get(key)
    if place is None:
        return False
    return cell in ctx.problem.cards[key].cells(place.day, place.period)


def _card_terms(ctx):
    """Koşullu (?) hücreler, yerleşmeyen kartlar ve öğretmen havuzu."""
    problem = ctx.problem
    by_lesson = {}
    for card in problem.cards:
        place = ctx.placements.get(card.key)
        name = ctx.label("lesson", card.lesson_id)
        if place is None:
            item = by_lesson.setdefault(("unplaced", card.lesson_id), _item("unplaced", "lesson", card.lesson_id, name, W_UNPLACED))
            _detail(item, f"{card.length} saatlik kart yerleşmedi", 1, W_UNPLACED, cards=[card.key])
            if not item["hints"]:
                item["hints"].append("Yerleşmeyen kart en ağır cezadır; nedenleri ve çözüm yolları için Bekleyenler sayfasına bakın.")
            continue
        maybe = [c for c in card.cells(place.day, place.period) if c in card.maybe_slots]
        if maybe:
            item = by_lesson.setdefault(("maybe", card.lesson_id), _item("maybe", "lesson", card.lesson_id, name, W_MAYBE))
            for d, s in maybe:
                _detail(item, f"{ctx.day(d)} {s + 1}. saat koşullu (?) işaretli", 1, W_MAYBE, cells=[(d, s)], cards=[card.key])
            if not item["hints"]:
                item["hints"].append("Bu saatler müsaitlikte “?” (mümkünse kullanma) işaretli. Saat uygunsa “açık” yapmak "
                                     "bu cezayı kaldırır.")
    for pool in problem.teacher_pools:
        for lesson_id in pool.lessons:
            hint, chosen = pool.hints.get(lesson_id), ctx.choice.get(lesson_id)
            if hint is not None and chosen is not None and hint != chosen:
                item = _item("teacher_changed", "lesson", lesson_id, ctx.label("lesson", lesson_id), W_TEACHER_CHANGED)
                _detail(item, f"{ctx.label('teacher', hint)} → {ctx.label('teacher', chosen)}", 1, W_TEACHER_CHANGED)
                by_lesson[("teacher_changed", lesson_id)] = item
    return list(by_lesson.values())


# --- çözücünün modeliyle ölçülen terimler --------------------------------------------------------


class _TaggedBuilder(cpsat._Builder):
    """Çözücünün kurucusu; her cezaya onu doğuran kuralın anahtarını (ör. ("rel", 3)) iliştirir."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tags = []
        self._rule = None

    def _penalize(self, category, weight, expr):
        before = len(self.penalties)
        super()._penalize(category, weight, expr)
        if len(self.penalties) > before:
            self.tags.append(self._rule)

    def _tagged(self, method, args, kwargs):
        self._rule = kwargs.get("rule")
        try:
            return method(*args, **kwargs)
        finally:
            self._rule = None

    def _limit(self, *args, **kwargs):
        return self._tagged(super()._limit, args, kwargs)

    def _at_least(self, *args, **kwargs):
        return self._tagged(super()._at_least, args, kwargs)

    def _violation(self, *args, **kwargs):
        return self._tagged(super()._violation, args, kwargs)

    def resource_conflicts(self):
        """Kartlar sabit olduğundan çakışma kısıtı cezayı etkilemez; çakışan (elle düzenlenmiş) program da ölçülsün."""


class _Unlimited(dict):
    """Derslik kapasitesi: sabit yerleşimde kapasite kısıtı cezayı etkilemez (bkz. resource_conflicts)."""

    def get(self, key, default=None):
        return 1 << 20


def _pinned_problem(problem, placements):
    """Kartları şu anki yerlerine (izinli başlangıç olarak) ekleyen kopya; önbellekteki problem değişmez."""
    pinned = copy.copy(problem)
    cards = []
    for card in problem.cards:
        place = placements.get(card.key)
        changes = {"hint": None}
        if place is not None:
            slot = (place.day, place.period)
            if card.fixed is not None and card.fixed != slot:
                changes["fixed"] = None
            if slot not in card.starts and changes.get("fixed", card.fixed) is None:
                changes["starts"] = [*card.starts, slot]
        cards.append(replace(card, **changes))
    pinned.cards = cards
    pinned.room_slots = _Unlimited()
    pinned.anchors, pinned.room_anchors, pinned.max_moves, pinned.forbidden_move_sets = {}, {}, None, []
    return pinned


def model_terms(problem, placements, choice=None, time_limit=30, full=True):
    """Sabitlenmiş modelin ceza terimleri; derslik ya da havuz seçimi modelle çelişirse onlar serbest bırakılır.
    full=False: yalnızca kart ilişkileri kurulur (öğretmen/sınıf kuralları saf Python katmanında; çok daha hızlı)."""
    result = _model_terms(problem, placements, choice, time_limit, True, full)
    if result["status"] == "infeasible":
        result = _model_terms(problem, placements, choice, time_limit, False, full)
        result["loose"] = True
    return result


def _model_terms(problem, placements, choice, time_limit, pin_choices, full):
    """Çözücünün (esnek kipteki) modelinde kartları sabitleyip ceza terimlerini okur.

    Dönüş: {"status", "terms": [(kategori, ağırlık, değer, kural)], "relaxed": [(kural, ad, aşım)], "wall_time"}.
    Esnek kip kullanılır: kesin kuralı aşan (elle düzenlenmiş) bir program da ölçülebilsin, aşım ayrı görünsün."""
    started = time.monotonic()
    choice = choice or {}
    pinned = _pinned_problem(problem, placements)
    builder = _TaggedBuilder(pinned, cpsat.RELAXED)
    if full:
        model = builder.build()
    else:
        model = builder.m
        builder.placement_vars()
        builder.rooms()
        builder.relationships()
        if builder.penalties:
            model.Minimize(sum(w * e for _, w, e in builder.penalties))
    for card in pinned.cards:
        place = placements.get(card.key)
        slot = (place.day, place.period) if place else None
        for start, var in builder.x[card.key].items():
            model.Add(var == int(start == slot))
        if place is None or not pin_choices:
            continue
        rooms = builder.y.get(card.key, {})
        for room in place.rooms:
            var = rooms.get(room)
            if var is not None and not isinstance(var, int):
                model.Add(var == 1)
    for lesson_id, zs in builder.z.items():
        chosen = choice.get(lesson_id)
        if chosen in zs and pin_choices:
            for teacher_id, var in zs.items():
                model.Add(var == int(teacher_id == chosen))
    solver = cpsat.cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_workers = 4
    status = solver.Solve(model)
    result = {"status": cpsat.STATUS_NAMES.get(status, "unknown"), "terms": [], "relaxed": [], "full": full}
    if status in (cpsat.cp_model.OPTIMAL, cpsat.cp_model.FEASIBLE):
        value = lambda e: e if isinstance(e, int) else solver.Value(e)  # noqa: E731
        for (category, weight, expr), rule in zip(builder.penalties, builder.tags):
            v = value(expr)
            if v:
                result["terms"].append((category, weight, int(v), rule))
        for rule, label, expr in builder.relaxed_slacks:
            v = value(expr)
            if v:
                result["relaxed"].append((rule, label, int(v)))
    result["wall_time"] = round(time.monotonic() - started, 2)
    return result


def _model_items(ctx, measured, validation):
    """İlişki ve esnetilen kural kalemleri (modelden ölçülen miktarlarla)."""
    problem = ctx.problem
    items = {}
    for category, weight, amount, rule in measured["terms"]:
        if category != "relationship" or not rule or rule[0] != "rel":
            continue
        index = rule[1]
        rel = problem.relationships[index]
        item = items.get(("rel", index))
        if item is None:
            item = items[("rel", index)] = _item("relationship", "relationship", rel.id, rel.name, weight)
            item["condition"] = rel.condition
        item["amount"] += amount
        item["penalty"] += weight * amount
    for (_, index), item in items.items():
        rel = problem.relationships[index]
        texts = [v.message for v in validation if v.code == "relationship" and v.ref == rel.id and v.message.startswith(rel.name)]
        for text in texts[:40]:
            item["details"].append({"text": text[len(rel.name) + 2:] if text.startswith(rel.name + ": ") else text,
                                    "amount": None, "weight": item["weight"], "penalty": None, "cells": [], "cards": []})
        if len(texts) > 40:
            item["details"].append({"text": f"… ve {len(texts) - 40} ihlal daha", "amount": None, "weight": item["weight"],
                                    "penalty": None, "cells": [], "cards": []})
        _relationship_hints(ctx, item, rel)
    relaxed = {}
    for rule, label, amount in measured["relaxed"]:
        key = rule if rule is not None else label
        item = relaxed.get(key)
        if item is None:
            owner, owner_id = ("relationship", problem.relationships[rule[1]].id) if rule and rule[0] == "rel" else (None, None)
            if rule and rule[0] in ("teacher_max", "teacher_gaps_day", "teacher_days", "teacher_consecutive", "teacher_min",
                                    "teacher_gaps_week"):
                owner, owner_id = "teacher", rule[1]
            elif rule and rule[0] in ("class_max", "class_min"):
                owner, owner_id = "class", rule[1]
            item = relaxed[key] = _item("relaxed", owner, owner_id, label or str(rule), W_RELAXED)
            item["hints"].append("Kesin bir kural bu programda sağlanmıyor; her aşım birimi "
                                 f"{W_RELAXED} puan. Ana görünümde “İhlalleri çöz” ya da Çözüm merkezinde “İhlalleri düzelt” "
                                 "ile giderilebilir; kural gerçekçi değilse gevşetilmelidir.")
        _detail(item, "aşım", amount, W_RELAXED)
    for item in relaxed.values():
        amount = item["amount"]
        item["details"] = [{"text": f"{amount} birim aşım", "amount": amount, "weight": W_RELAXED, "penalty": amount * W_RELAXED,
                            "cells": [], "cards": []}]
    return list(items.values()) + list(relaxed.values())


def _relationship_hints(ctx, item, rel):
    """Kart sayısı ve müsaitlikten hesaplanabilen, kaçınılmaz ihlal durumları."""
    problem = ctx.problem
    hints = item["hints"]
    cond, n = rel.condition, rel.param
    for g, keys in enumerate(rel.groups):
        owner = rel.owners[g] if g < len(rel.owners) and rel.owners[g] else None
        who = f"{problem.label(*owner)}: " if owner else ""
        days = _possible_days(ctx, keys)
        hours = sum(problem.cards[k].length for k in keys)
        if cond in ("max_per_day", "different_days"):
            limit = 1 if cond == "different_days" else n
            if days and len(keys) > limit * len(days):
                hints.append(f"{who}{len(keys)} kart var, ama kartlar yalnızca {len(days)} güne konabiliyor; günde en fazla "
                             f"{limit} kartla en az {len(keys) - limit * len(days)} aşım kaçınılmaz.")
        elif cond == "min_days" and days and len(days) < n:
            hints.append(f"{who}kartlar en az {n} güne yayılmalı ama müsaitliğe göre yalnızca {len(days)} güne konabiliyor.")
        elif cond == "min_days" and len(keys) < n:
            hints.append(f"{who}en az {n} güne yayılması isteniyor ama yalnızca {len(keys)} kart var.")
        elif cond in ("max_days", "range_max_days") and hours > n * problem.periods:
            hints.append(f"{who}{hours} saat en fazla {n} güne sığmaz (günde {problem.periods} saat).")
        elif cond == "map_min_week":
            if hours < n:
                hints.append(f"{who}işaretli saatlerde haftada en az {n} saat isteniyor ama toplam yalnızca {hours} saat var.")
        elif cond == "min_gap_days" and len(keys) > 1:
            need = (len(keys) - 1) * (n + 1) + 1
            if need > problem.days:
                hints.append(f"{who}{len(keys)} kart arasında en az {n} boş gün için {need} gün gerekir; haftada {problem.days} gün var.")
    if cond in ("same_time", "same_day", "consecutive", "consecutive_ordered") and len(rel.groups) > 1:
        first, *others = rel.groups
        impossible = 0
        for other in others:
            for a, b in zip(first, other):
                ca, cb = problem.cards[a], problem.cards[b]
                if cond == "same_time" and not set(ca.starts) & set(cb.starts):
                    impossible += 1
                elif cond == "same_day" and not {d for d, _ in ca.starts} & {d for d, _ in cb.starts}:
                    impossible += 1
        if impossible:
            hints.append(f"{impossible} kart çiftinin müsaitlikte ortak {'saati' if cond == 'same_time' else 'günü'} yok; "
                         "bu çiftler için ihlal kaçınılmaz.")
        sizes = {len(g) for g in rel.groups}
        if len(sizes) > 1:
            hints.append(f"Kümelerdeki kart sayıları farklı ({', '.join(str(s) for s in sorted(sizes))}); fazla kartlar eşleşmez.")
    hints.append(f"Bu ilişkinin önemi ihlal başına {item['weight']} puan. Kural sizin için o kadar önemli değilse önemini "
                 "düşürmek, gerçekçi değilse koşulunu gevşetmek bu cezayı azaltır.")


# --- toplu döküm -------------------------------------------------------------------------------


# Esnek kipte ağır cezalı aşıma dönüşen kesin kurallar (doğrulayıcının kodlarıyla); ilişkiler ayrıca ele alınır.
HARD_RULE_CODES = {"lesson_spread", "teacher_daily_max", "teacher_day_gaps", "teacher_week_gaps", "teacher_days",
                   "teacher_consecutive", "teacher_min", "class_max", "class_min"}


def breakdown(problem, placements, choice=None, day_names=None, measure="auto", time_limit=30):
    """Yerleşimin ceza dökümü.

    choice: öğretmen havuzunda ders → öğretmen (verilmezse havuzun şu anki öğretmenleri).
    measure: "auto" — çözücü modeli yalnızca gerekirse kurulur (önemi kesin olmayan ilişki ya da aşılan kesin kural
        varsa; ilişki dışındaki aşımlarda tam model, yoksa yalnızca ilişkiler). "full" — her zaman tam model (saf
        Python kalemleri de modelle karşılaştırılır, bkz. "mismatch"). False — model hiç kurulmaz.
    Dönüş: {"total", "kinds": [...], "items": [...], "exact", "model", "mismatch"}."""
    from .solver.validate import validate

    if choice is None:
        choice = {lesson_id: t for pool in problem.teacher_pools for lesson_id, t in pool.hints.items()}
    ctx = _Context(problem, placements, choice, day_names)
    items = _teacher_terms(ctx) + _class_terms(ctx) + _card_terms(ctx)
    violations = validate(problem, placements)[0] if measure else []
    full = measure == "full" or any(v.level == "hard" and v.code in HARD_RULE_CODES for v in violations)
    needed = full or any(r.weight is not None for r in problem.relationships) or any(
        v.code == "relationship" and v.level == "hard" for v in violations)
    measured = None
    mismatch = {}
    if measure and needed:
        measured = model_terms(problem, placements, choice, time_limit=time_limit, full=full)
        if measured["status"] in ("optimal", "feasible"):
            items += _model_items(ctx, measured, violations)
            if full:
                # Saf Python kalemleri modelle karşılaştırılır (tanım aynı olmalı; test de bunu doğrular).
                model_totals = defaultdict(int)
                for category, weight, amount, _ in measured["terms"]:
                    model_totals[category] += weight * amount
                own = defaultdict(int)
                for item in items:
                    own[item["kind"]] += item["penalty"]
                mismatch = {k: (own.get(k, 0), model_totals.get(k, 0)) for k in set(own) | set(model_totals)
                            if own.get(k, 0) != model_totals.get(k, 0)}
    items = [i for i in items if i["penalty"]]
    items.sort(key=lambda i: (-i["penalty"], i["name"]))
    totals = defaultdict(lambda: [0, 0])
    for item in items:
        totals[item["kind"]][0] += item["penalty"]
        totals[item["kind"]][1] += 1
    total = sum(t for t, _ in totals.values())
    order = {k: i for i, k in enumerate(KIND_ORDER)}
    kinds = [{"kind": k, "label": KIND_LABELS.get(k, k), "total": t, "count": c,
              "share": _share(t, total), "width": max(1, round(100 * t / max(v[0] for v in totals.values())))}
             for k, (t, c) in sorted(totals.items(), key=lambda kv: (-kv[1][0], order.get(kv[0], 99)))]
    # En çok katkı yapanlar: aynı öğretmen / sınıf / ilişki / dersin kalemleri bir arada
    owners = {}
    for item in items:
        key = (item["owner"], item["owner_id"]) if item["owner"] else ("rule", item["name"])
        entry = owners.setdefault(key, {"owner": item["owner"], "owner_id": item["owner_id"], "name": item["name"],
                                        "total": 0, "items": []})
        entry["total"] += item["penalty"]
        entry["items"].append(item)
    contributors = sorted(owners.values(), key=lambda o: (-o["total"], o["name"]))
    for entry in contributors:
        entry["kinds"] = sorted({i["kind"] for i in entry["items"]})
        entry["share"] = _share(entry["total"], total)
    return {
        "total": total,
        "kinds": kinds,
        "items": items,
        "contributors": contributors,
        # Model gerekmediyse saf Python hesabı tamdır; gerektiyse modelin en iyi değeri kanıtlanmış olmalı.
        "exact": bool(measure) and (measured is None or measured["status"] == "optimal"),
        "model": measured and {"status": measured["status"], "wall_time": measured["wall_time"]},
        "mismatch": mismatch,
    }


# --- sayfa ---------------------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cache = {}  # program → (damga, döküm)
CACHE_SIZE = 6


def timetable_breakdown(timetable):
    """Kayıtlı programın dökümü (problem önbellekten; aynı veri ve yerleşim için sonuç bellekte tutulur)."""
    from .problem_cache import _stamp as data_stamp
    from .problem_cache import problem_for
    from .services import placements_of

    problem = problem_for(timetable)
    placements = placements_of(problem, timetable)
    positions = tuple(sorted((k, p.day, p.period, p.rooms) for k, p in placements.items()))
    stamp = (data_stamp(timetable), hash(positions))
    with _cache_lock:
        entry = _cache.get(timetable.pk)
        if entry and entry[0] == stamp:
            return entry[1]
    data = breakdown(problem, placements, day_names=timetable.school.day_names)
    with _cache_lock:
        _cache[timetable.pk] = (stamp, data)
        while len(_cache) > CACHE_SIZE:
            _cache.pop(next(iter(_cache)))
    return data


OWNER_LABELS = {"teacher": "Öğretmen", "class": "Sınıf", "relationship": "Kart ilişkisi", "lesson": "Ders", None: "Kural"}


def breakdown_view(request, pk):
    """Çözüm merkezi → Ceza dökümü: kural türüne göre toplamlar, en çok katkı yapanlar ve ne yapılabilir."""
    from django.shortcuts import get_object_or_404, render
    from django.urls import reverse

    from .models import Timetable
    from .views import _nav

    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    data = timetable_breakdown(timetable)
    grid_url = reverse("timetable:timetable_detail", args=[pk])
    short = {c.id: c.short or c.name for c in school.classes.all()}
    contributors = []
    for entry in data["contributors"]:
        link = None
        if entry["owner"] == "teacher":
            link = f"{grid_url}?tur=ogretmen&ara={quote(entry['name'])}"
        elif entry["owner"] == "class":
            link = f"{grid_url}?tur=sinif&ara={quote(short.get(entry['owner_id'], entry['name']))}"
        elif entry["owner"] == "relationship" and entry["owner_id"]:
            link = reverse("timetable:data_edit", args=[school.pk, "kart-iliskileri", entry["owner_id"]])
        elif entry["owner"] == "lesson" and "unplaced" in entry["kinds"]:
            link = reverse("timetable:pending", args=[pk])
        contributors.append({**entry, "link": link, "owner_label": OWNER_LABELS.get(entry["owner"], "")})
    return render(request, "timetable/penalty_breakdown.html", _nav(
        school, "solution", timetable=timetable, data=data, contributors=contributors, grid_url=grid_url,
        differs=timetable.objective is not None and timetable.objective != data["total"],
        center_url=reverse("timetable:solution_center", args=[pk]),
    ))
