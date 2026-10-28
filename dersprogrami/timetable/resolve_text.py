"""Çözüm merkezi: yazıyla istek ("Mehmet salı 1. saat dersini kaydır") → form alanları.

Kural tabanlıdır; dış servise veri gitmez. Programdaki öğretmen, sınıf, ders kodu ve derslik adları
ile gün/saat ifadeleri tanınır. Anlaşılan her parça kullanıcıya gösterilir; eksik ya da belirsiz
kalan (ör. iki Mehmet) için açıklama döner ve form o haliyle doldurulur.
"""

import re

DAYS = [
    ("pazartesi", "pzt"), ("salı", "sal"), ("çarşamba", "çar", "carsamba", "çarşamba"), ("perşembe", "per", "persembe"),
    ("cuma", "cum"), ("cumartesi", "cmt"), ("pazar", "paz"),
]
NOT_COMING = r"gelemi|geleme|gelemez|gelmeyecek|gelmiyor|izinli|müsait değil|musait degil|raporlu|yok\b|olmayacak|ders veremez"
ROOM_OFF = r"kullanılam|kullanilam|kapalı|kapali|tadilat|arızalı|arizali|boşaltıl"
PLACE = r"\b(al|alın|alalım|taşı|tası|taşıyın|koy|getir|yerleştir|kaydır)\w*\b"
SHIFT = r"kaydır|kaydir|değiştir|degistir|başka saate|baska saate|çıkar|cikar|oynat|taşı|tasi"


def norm(text):
    return (text or "").replace("İ", "i").replace("I", "ı").lower()


def _words(text):
    return re.findall(r"[\wçğıöşü\.]+", text)


def _day_of(word):
    for i, names in enumerate(DAYS):
        for n in names:
            if word == n or (len(word) > len(n) and word.startswith(n) and n == names[0]):
                return i  # "salıya", "cumaya", "perşembeden" gibi ekli halleri de
    return None


def _time_mentions(text, period_count, periods=None):
    """Metindeki (gün, [saatler]) ifadeleri sırasıyla. Saat yoksa [] (tüm gün değil, belirsiz)."""
    tokens = list(re.finditer(r"[\wçğıöşü]+", text))
    out = []
    for i, tok in enumerate(tokens):
        day = _day_of(tok.group())
        if day is None:
            continue
        # gün adından sonraki ~6 sözcükte saat ifadesi aranır (bir sonraki gün adına kadar)
        tail_end = len(text)
        for nxt in tokens[i + 1:]:
            if _day_of(nxt.group()) is not None:
                tail_end = nxt.start()
                break
        tail = text[tok.end():tail_end][:60]
        hours = _hours(tail, period_count, periods)
        out.append((day, hours, tok.start()))
    return out


def _hours(tail, period_count, periods=None):
    if re.search(r"tüm gün|tum gun|bütün gün|butun gun|gün boyu|gun boyu|tam gün", tail):
        return list(range(period_count))
    found = []
    if re.search(r"\bilk saat", tail):
        found.append(0)
    if re.search(r"\bson saat", tail):
        found.append(period_count - 1)
    if periods and re.search(r"öğleden sonra|ogleden sonra", tail):
        found += [p.index for p in periods if p.start_time and p.start_time.hour >= 12]
    if periods and re.search(r"\bsabah", tail):
        found += [p.index for p in periods if p.start_time and p.start_time.hour < 12]
    # "1-2", "3 ve 4", "1, 2", "5.", "3'e", "2 saat" (sayının ardından "saat" ya da nokta/kesme)
    m = re.match(r"[\s,]*((?:\d{1,2}\s*(?:\.|'\w*|’\w*)?\s*(?:-|–|ve|,|ile)?\s*)+)", tail)
    if m:
        nums = [int(x) for x in re.findall(r"\d{1,2}", m.group(1))]
        if re.search(r"\d\s*[-–]\s*\d", m.group(1)) and len(nums) == 2 and nums[0] < nums[1]:
            nums = list(range(nums[0], nums[1] + 1))
        found += [n - 1 for n in nums if 1 <= n <= period_count]
    return sorted(set(found))


def _match_teachers(school, text):
    teachers = list(school.teachers.all())
    words = set(_words(text))
    full = [t for t in teachers if norm(t.full_name) in text or (t.short and norm(t.short) in words)]
    if full:
        return full
    by_first = [t for t in teachers if norm(t.first_name).split()[0] in words] if teachers else []
    by_last = [t for t in teachers if norm(t.last_name) in words]
    both = [t for t in by_first if t in by_last]
    return both or by_last or by_first


def parse(school, timetable, text):
    """Dönüş: {"form": {...}, "understood": [..], "problems": [..], "candidates": {...}}."""
    from .resolve import _where

    raw = text
    text = norm(text)
    periods = list(school.periods.all())
    P = len(periods)
    understood, problems = [], []
    form = {"kind": None, "card": None, "teacher": None, "room": None, "day": 0, "period": 0, "periods": [],
            "max_moves": 4, "same_day": bool(re.search(r"aynı gün|ayni gun", text))}
    m = re.search(r"en fazla (\d+)", text)
    if m:
        form["max_moves"] = max(1, min(10, int(m.group(1))))
        understood.append(f"en fazla {form['max_moves']} değişiklik")

    words = set(_words(text))
    classes = [c for c in school.classes.all() if norm(c.short or "") in words or norm(c.name) in words]
    subjects = [s for s in school.subjects.all() if s.short and norm(s.short) in words]
    rooms = [r for r in school.classrooms.all() if norm(r.name) in text or (r.short and norm(r.short) in words)]
    teachers = _match_teachers(school, text)
    times = _time_mentions(text, P, periods)

    # İstek türü
    to_target = re.search(r"\d*\s*('|’)?(y?[ea]|n[ea]|[ae]) (al|taşı|tası|koy|getir|yerleştir)", text) or re.search(r"\b(al|taşı|koy|getir)\b", text)
    if rooms and re.search(ROOM_OFF, text) and not teachers:
        form["kind"] = "room"
    elif re.search(NOT_COMING, text):
        form["kind"] = "teacher"
    elif len(times) >= 2 or (times and to_target and not re.search(r"kaydır|kaydir", text)):
        form["kind"] = "place"
    elif re.search(SHIFT, text) or times:
        form["kind"] = "shift"
    if form["kind"] is None:
        problems.append("Ne yapılacağı anlaşılmadı: “kaydır”, “… saate al”, “gelemiyor” ya da “kullanılamıyor” gibi bir ifade kullanın.")
        form["kind"] = "shift"
    kind_text = {"shift": "dersi kaydır", "place": "dersi başka saate al", "teacher": "öğretmen gelemiyor", "room": "derslik kullanılamıyor"}
    understood.append(kind_text[form["kind"]])

    if len(teachers) > 1 and times and form["kind"] in ("shift", "place"):
        # Aynı adlı birden çok öğretmen: söylenen saatte dersi olan tek kişiyse o kastedilmiştir.
        day, hours = (times[0][0], times[0][1]) if not (form["kind"] == "place" and len(times) == 1) else (None, [])
        if day is not None:
            busy = []
            for t in teachers:
                for c in timetable.cards.filter(lesson__teachers=t, day=day):
                    if not hours or set(range(c.period, c.period + c.length)) & set(hours):
                        busy.append(t)
                        break
            if len(busy) == 1:
                understood.append(f"(o saatte dersi olan tek {busy[0].first_name})")
                teachers = busy
            elif busy:
                teachers = busy
    candidates = [(t.id, t.full_name) for t in teachers[:8]] if len(teachers) > 1 else []
    if len(teachers) > 1:
        problems.append("Birden çok öğretmen eşleşti: " + ", ".join(t.full_name for t in teachers[:6]) + ". Soldan doğru olanı seçin ya da soyadını da yazın.")
    elif teachers:
        form["teacher"] = teachers[0].id
        understood.append(f"öğretmen: {teachers[0].full_name}")
    if rooms:
        form["room"] = rooms[0].id
        if form["kind"] == "room":
            understood.append(f"derslik: {rooms[0]}")
    if classes:
        understood.append("sınıf: " + ", ".join(c.short or c.name for c in classes))
    if subjects:
        understood.append("ders: " + ", ".join(s.short for s in subjects))

    source = times[0] if times else None
    target = times[1] if len(times) > 1 else None
    if form["kind"] == "place" and len(times) == 1:
        source, target = None, times[0]  # "… dersini çarşamba 3'e al": tek zaman hedeftir
    if form["kind"] in ("teacher", "room"):
        if source is None:
            problems.append("Gün anlaşılmadı (ör. “salı 1-4”, “perşembe tüm gün”).")
        else:
            form["day"] = source[0]
            form["periods"] = source[1] or list(range(P))
            understood.append(f"{school.day_names[source[0]]} " + (", ".join(str(p + 1) for p in form["periods"]) + ". saatler" if source[1] else "tüm gün"))
        if form["kind"] == "teacher" and not teachers:
            problems.append("Öğretmen adı anlaşılmadı.")
        if form["kind"] == "room" and not rooms:
            problems.append("Derslik adı anlaşılmadı.")
        return {"form": form, "understood": understood, "problems": problems, "raw": raw, "candidates": candidates}

    # Kaydır / şuraya al: kartı bul
    cards = timetable.cards.filter(day__isnull=False).select_related("lesson__subject").prefetch_related("lesson__classes")
    if teachers:
        cards = cards.filter(lesson__teachers__in=teachers)
    if classes:
        cards = cards.filter(lesson__classes__in=classes)
    if subjects:
        cards = cards.filter(lesson__subject__in=subjects)
    cards = list(cards.distinct())
    if source is not None:
        day, hours = source[0], source[1]
        cards = [c for c in cards if c.day == day and (not hours or set(range(c.period, c.period + c.length)) & set(hours))]
    if not (teachers or classes or subjects):
        problems.append("Hangi ders olduğu anlaşılmadı: öğretmen, sınıf (ör. 1SVN) ya da ders kodu (ör. ASK203) yazın.")
    elif not cards:
        problems.append("Bu bilgilere uyan ders programda bulunamadı.")
    elif len(cards) > 1:
        problems.append("Birden çok ders uyuyor: " + "; ".join(
            f"{c.lesson.subject.short} {', '.join(x.short or x.name for x in c.lesson.classes.all())} {_where(c.day, c.period, c.length)}" for c in cards[:6])
            + ". Saat ya da sınıfı da yazın, ya da soldan seçin.")
        form["card"] = cards[0].id
    else:
        card = cards[0]
        form["card"] = card.id
        if not form["teacher"]:
            form["teacher"] = card.lesson.teachers.values_list("id", flat=True).first()
        understood.append(f"ders: {card.lesson.subject.short or card.lesson.subject.name} "
                          f"({', '.join(x.short or x.name for x in card.lesson.classes.all())}) {_where(card.day, card.period, card.length)}")
    if form["kind"] == "place":
        if target is None or not target[1]:
            problems.append("Hedef saat anlaşılmadı (ör. “çarşamba 3'e al”).")
        else:
            form["day"], form["period"] = target[0], target[1][0]
            understood.append(f"hedef: {school.day_names[target[0]]} {target[1][0] + 1}. saat")
    return {"form": form, "understood": understood, "problems": problems, "raw": raw, "candidates": candidates}
