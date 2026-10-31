"""Müsaitlik değişince yerel onarım.

Bir öğretmenin, sınıfın, dersliğin, ders adının ya da dersin müsaitliği kaydedilince (kayıt düzenleyici,
toplu müsaitlik, aSc'den müsaitlik aktarımı, onaylanan müsaitlik isteği) aktif programda artık kapalı
saate düşen kartlar bulunur ve bir uyarıyla gösterilir. "En az değişiklikle onar" bu kartları kademeli
olarak genişleyen bir alanda yeniden yerleştirir; alan dışındaki kartlar yerinde sabit kalır:

1. Yalnızca etkilenen kartlar serbest; programda önceden çakışan kartlar varsa (sabitken çözüm olmaz)
   bir sonraki denemede onlar da serbest bırakılır.
2. Etkilenen kartların öğretmen, sınıf/grup ve dersliklerinin bütün haftası serbest.
3. Bir halka daha (komşuların haftası).
4. Olmazsa standart onarım: bütün yerleşmiş kartlar serbest (ana görünümdeki "İhlalleri çöz" gibi).

Her adımda cpsat.minimal_repair kullanılır (önce ihlal, sonra en az hareket). Kabul şartı: hedef kartların
hiçbiri kapalı saatte kalmaz ve yeni bir kesin ihlal doğmaz. Uygulamadan önce otomatik versiyon alınır;
değişiklik "Geri al" ya da versiyon geçmişiyle geri alınabilir.
"""

from collections import defaultdict

from django.template.loader import render_to_string
from django.urls import reverse

from .models import Availability
from .refs import DAY_SHORT

SESSION_KEY = "avail-repair-{}"  # okul: son kayıtta yeni kapalı saate düşen kartlar
RESULT_KEY = "avail-repair-result-{}"  # program: son onarımın sonucu
ALERT_LIMIT = 8  # uyarıda gösterilen en fazla kart satırı

# (açıklama, serbest alan, süre sn)
TIERS = (
    ("yalnızca etkilenen dersler", "targets", 8),
    ("etkilenen dersler ve zaten çakışan dersler", "seeds", 8),
    ("etkilenen öğretmen, sınıf ve dersliklerin haftası", "ring1", 15),
    ("komşu derslerin haftası", "ring2", 20),
    ("tüm program (standart onarım)", "all", 40),
)


# --- tespit ----------------------------------------------------------------------------------------

def _closed_index(school):
    """{(alan, kimlik): {(gün, saat), ...}} yalnızca yasak (kapalı) hücreler; okul geneli ("school", None)."""
    fields = Availability.TARGET_FIELDS
    index = defaultdict(set)
    rows = Availability.objects.filter(school=school, state=Availability.NO).values_list(*(f + "_id" for f in fields), "day", "period")
    for row in rows:
        target = next(((f, v) for f, v in zip(fields, row) if v), ("school", None))
        index[target].add((row[-2], row[-1]))
    return index


def _card_entities(card):
    lesson = card.lesson
    out = [("teacher", t.id) for t in lesson.teachers.all()]
    out += [("school_class", c.id) for c in lesson.classes.all()]
    out += [("classroom", r) for r in card.room_ids]
    out += [("subject", lesson.subject_id), ("lesson", lesson.id), ("school", None)]
    return out


def _where(day, period, length):
    end = f"–{period + length}" if length > 1 else ""
    return f"{DAY_SHORT[day] if day < len(DAY_SHORT) else day + 1} {period + 1}{end}"


def _names(school, entities):
    """Varlıkların görünen adları: {(alan, kimlik): ad}."""
    from .models import Classroom, Lesson, SchoolClass, Subject, Teacher

    ids = defaultdict(set)
    for field, obj_id in entities:
        ids[field].add(obj_id)
    names = {("school", None): "Okul geneli"}
    for t in Teacher.objects.filter(school=school, pk__in=ids["teacher"]):
        names[("teacher", t.id)] = t.full_name
    for c in SchoolClass.objects.filter(school=school, pk__in=ids["school_class"]):
        names[("school_class", c.id)] = c.short or c.name
    for r in Classroom.objects.filter(school=school, pk__in=ids["classroom"]):
        names[("classroom", r.id)] = str(r)
    for s in Subject.objects.filter(school=school, pk__in=ids["subject"]):
        names[("subject", s.id)] = s.short or s.name
    for lesson in Lesson.objects.filter(school=school, pk__in=ids["lesson"]).select_related("subject"):
        names[("lesson", lesson.id)] = f"{lesson.subject.short or lesson.subject.name} dersi"
    return names


def conflicts(timetable, entities=None):
    """Programda kapalı saate düşen yerleşmiş kartlar. entities verilirse yalnızca bu varlıkların kartları ve
    yalnızca bu varlıkların kapattığı hücreler sayılır. Dönüş: gün/saate göre sıralı satırlar."""
    if timetable is None or not timetable.has_grid:
        return []
    school = timetable.school
    closed = _closed_index(school)
    wanted = set(entities) if entities is not None else None
    if wanted is not None and not wanted:
        return []
    qs = timetable.cards.filter(day__isnull=False).select_related("lesson__subject").prefetch_related("lesson__teachers", "lesson__classes")
    hits = []
    for card in qs:
        cells = {(card.day, card.period + i) for i in range(card.length)}
        culprits = [e for e in _card_entities(card) if (wanted is None or e in wanted) and closed.get(e, set()) & cells]
        if culprits:
            hits.append((card, culprits))
    names = _names(school, {e for _, culprits in hits for e in culprits})
    out = []
    for card, culprits in sorted(hits, key=lambda h: (h[0].day, h[0].period, h[0].id)):
        who = ", ".join(dict.fromkeys(names.get(e, "?") for e in culprits))
        subject = card.lesson.subject.short or card.lesson.subject.name
        classes = ", ".join(c.short or c.name for c in card.lesson.classes.all())
        where = _where(card.day, card.period, card.length)
        out.append({
            "card_id": card.id, "who": who, "where": where, "subject": subject, "classes": classes, "locked": card.locked,
            "text": f"{who}: {where} {subject}{' ' + classes if classes else ''} artık kapalı saatte",
        })
    return out


class Watch:
    """Müsaitlik kaydından önce oluşturulur; kayıttan sonra report() yeni kapalı saate düşen kartları uyarı
    olarak döndürür (yoksa boş metin)."""

    def __init__(self, school, entities):
        self.school = school
        self.entities = {e for e in entities if e is not None and (e[0] == "school" or e[1])}
        self.timetable = school.current_timetable() if self.entities else None
        self.before = {c["card_id"] for c in conflicts(self.timetable, self.entities)} if self.timetable else set()

    def new_conflicts(self):
        if self.timetable is None:
            return []
        return [c for c in conflicts(self.timetable, self.entities) if c["card_id"] not in self.before]

    def report(self, request):
        items = self.new_conflicts()
        if not items:
            return ""
        request.session[SESSION_KEY.format(self.school.pk)] = {"timetable": self.timetable.pk, "cards": [c["card_id"] for c in items]}
        return alert_html(request, self.timetable, items)


def alert_html(request, timetable, items):
    return render_to_string("timetable/availability_alert.html", {
        "timetable": timetable, "items": items[:ALERT_LIMIT], "more": max(0, len(items) - ALERT_LIMIT), "count": len(items),
        "card_ids": [c["card_id"] for c in items],
    }, request=request)


def notify(request, watch):
    """Normal (yönlendirmeli) kayıtlarda: yeni çakışma varsa uyarı mesajı ekler. Dönüş: uyarı metni."""
    from django.contrib import messages
    from django.utils.safestring import mark_safe

    html = watch.report(request)
    if html:
        messages.warning(request, mark_safe(html))
    return html


# --- onarım ----------------------------------------------------------------------------------------

def _blocked(problem, placements, key):
    card, place = problem.cards[key], placements.get(key)
    if place is None:
        return False
    if (place.day, place.period) not in card.starts:
        return True
    return any(cell in problem.room_blocked.get(r, ()) for r in place.rooms for cell in card.cells(place.day, place.period))


def _attempt(center, free, seconds):
    """Serbest kümedeki kartlar yer değiştirebilir, diğer yerleşmiş kartlar sabit. Yerleşmemiş kartlar bu işin
    konusu değildir. Dönüş: (taşınan anahtarlar, yeni yerleşim) ya da None."""
    from .resolve import _subproblem
    from .solver import cpsat

    full, placements = center.full, center.placements
    sub, new_key = _subproblem(full, set(placements))
    old_of = {v: k for k, v in new_key.items()}
    anchors, room_anchors = {}, {}
    for card in sub.cards:
        old = old_of[card.key]
        place = placements[old]
        if card.fixed is not None:
            continue
        if old in free:
            card.hint = (place.day, place.period, place.room)
            anchors[card.key] = (place.day, place.period)
            if place.rooms:
                room_anchors[card.key] = tuple(place.rooms)
        else:
            card.fixed, card.fixed_room, card.fixed_rooms = (place.day, place.period), place.room, place.rooms
    sub.anchors, sub.room_anchors = anchors, room_anchors
    after, _info = cpsat.minimal_repair(sub, time_limit=seconds, place_all=True)
    if after is None:
        return None
    result = dict(placements)
    moved = set()
    for key, place in after.items():
        old = old_of[key]
        before = placements.get(old)
        if before is None or (before.day, before.period) != (place.day, place.period):
            moved.add(old)
        result[old] = place
    return moved, result


def repair(timetable, card_ids=None, time_scale=1.0):
    """Kapalı saatteki kartları en az değişiklikle yeniden yerleştiren öneri (uygulanmaz).
    card_ids: onarılacak kartlar (verilmezse kapalı saatteki bütün kilitsiz kartlar).
    Dönüş: resolve.Center._report biçiminde öneri + "tier" (kullanılan alan) ve "skipped_locked"."""
    from .resolve import Center, ResolveError, _conflicting, _neighbours
    from .solver.validate import validate

    center = Center(timetable)
    full, placements = center.full, center.placements
    blocked = {k for k in placements if full.cards[k].fixed is None and _blocked(full, placements, k)}
    # Kilitli kart çözücüde sabittir (kapalı saat ona uygulanmaz); konumu bizim tespitimizde yine kapalıdır.
    wanted = {center.key_of[c] for c in card_ids if c in center.key_of} if card_ids is not None else None
    locked = []
    for c in conflicts(timetable, None):
        k = center.key_of.get(c["card_id"])
        if k is not None and full.cards[k].fixed is not None and (wanted is None or k in wanted):
            locked.append(c["text"])
    targets = blocked if wanted is None else blocked & wanted
    if not targets:
        if locked:
            raise ResolveError("Kapalı saatteki dersler kilitli; taşınabilmeleri için önce kilitlerini açın.")
        raise ResolveError("Aktif programda kapalı saate düşen (taşınabilir) ders yok.")
    for k in targets:
        if not full.cards[k].starts:
            raise ResolveError(f"{full.label('lesson', full.cards[k].lesson_id)} için açık hiçbir saat kalmadı; müsaitliği gözden geçirin.")
    baseline_v, baseline_stats = validate(full, placements)
    baseline_hard = {v.message for v in baseline_v if v.level == "hard"}
    clashing = _conflicting(full, placements) & set(placements)
    ring1 = (_neighbours(full, placements, targets) & set(placements)) | clashing
    areas = {"targets": targets, "seeds": targets | clashing, "ring1": ring1, "ring2": _neighbours(full, placements, ring1) & set(placements), "all": set(placements)}
    tried = None
    for label, area, seconds in TIERS:
        free = areas[area]
        if free == tried:
            continue  # alan genişlemedi: aynı denemeyi tekrarlama
        tried = free
        result = _attempt(center, free, max(2, round(seconds * time_scale)))
        if result is None:
            continue
        moved, after = result
        if any(_blocked(full, after, k) for k in targets):
            continue
        after_v, _ = validate(full, after)
        if any(v.level == "hard" and v.message not in baseline_hard for v in after_v):
            continue
        proposal = center._report(after, moved, baseline_v, baseline_stats)
        proposal["tier"] = label
        proposal["targets"] = len(targets)
        proposal["skipped_locked"] = locked
        return proposal
    raise ResolveError("Kapalı saatteki dersler, programda yeni çakışma doğurmadan taşınamadı. Çözüm merkezinde "
                       "“İhlalleri düzelt” ile ya da müsaitliği gözden geçirerek yeniden deneyin.")


def run(timetable, card_ids=None, user=None, time_scale=1.0):
    """Onarımı hesaplar ve uygular: önce otomatik versiyon, sonra kartlar (geri alınabilir). Dönüş: sonuç özeti."""
    from . import resolve, versions

    proposal = repair(timetable, card_ids, time_scale=time_scale)
    # Değişiklik öncesi hâl versiyon olarak kalsın (son versiyondan beri değişiklik yoksa o versiyon yeterli).
    before = versions.save_version(timetable, user=user, note="Müsaitlik onarımı öncesi otomatik kayıt", auto=True) or versions.latest(timetable)
    label = f"Müsaitlik onarımı ({proposal['targets']} ders)"
    if proposal["moves"]:
        resolve.apply(timetable, proposal, label, user)
    return {
        "count": proposal["count"], "targets": proposal["targets"], "tier": proposal["tier"],
        "moves": [{"text": f"{m['subject']} ({m['classes']}) · {m['teachers']}", "from": m["from"], "to": m["to"],
                   "room": f"{m['room_from']} → {m['room_to']}" if m["room_from"] != m["room_to"] else "",
                   "time_moved": m["time_moved"]} for m in proposal["moves"]],
        "fixed": len(proposal["fixed_violations"]), "skipped_locked": proposal["skipped_locked"],
        "version": before.number if before else None,
    }


# --- ekran -----------------------------------------------------------------------------------------

def repair_view(request, pk):
    """Kapalı saatteki dersler ve "En az değişiklikle onar"."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect, render

    from .models import Timetable
    from .resolve import ResolveError
    from .views import _nav

    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    school = timetable.school
    url = reverse("timetable:availability_repair", args=[timetable.pk])
    if request.method == "POST":
        if not timetable.has_grid:
            messages.error(request, "Bu program düzenlenemez.")
            return redirect(url)
        ids = [int(x) for x in request.POST.getlist("kart") if x.isdigit()] or None
        try:
            result = run(timetable, ids, request.user)
        except ResolveError as exc:
            messages.error(request, str(exc))
            return redirect(url)
        request.session[RESULT_KEY.format(timetable.pk)] = result
        request.session.pop(SESSION_KEY.format(school.pk), None)
        messages.success(request, f"Müsaitlik onarımı: {result['count']} kart taşındı ({result['tier']}). "
                                  "Geri almak için ana görünümde “Geri al” ya da Versiyonlar.")
        return redirect(f"{url}?sonuc=1")
    result = request.session.get(RESULT_KEY.format(timetable.pk)) if request.GET.get("sonuc") == "1" else None
    items = conflicts(timetable)
    recent = request.session.get(SESSION_KEY.format(school.pk)) or {}
    fresh = set(recent.get("cards") or []) if recent.get("timetable") == timetable.pk else set()
    for item in items:
        item["new"] = item["card_id"] in fresh
    return render(request, "timetable/availability_repair.html", _nav(
        school, "timetable", timetable=timetable, items=items, result=result, new_count=sum(1 for i in items if i["new"]),
        movable=sum(1 for i in items if not i["locked"]),
    ))
