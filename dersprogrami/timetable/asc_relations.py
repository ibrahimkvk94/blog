"""aSc kart ilişkilerini yapıştırarak aktarma.

aSc'de Kart ilişkileri listesi tarayıcıda "İncele → kopyala" ile HTML olarak ya da tablodan
seçilip metin (sekmeyle ayrılmış) olarak yapıştırılır. Her satır: Uygula ("Tüm Sınıflar - BİL103,
BİL103" ya da "a_32"), Tür, Parametreler, önem simgesi ve devre dışı simgesi.

aSc satırı yalnızca ders kodlarını gösterir; hangi derslerin kastedildiği programdaki derslerden
çıkarılır. Ör. "Dersler ardarda – BİL103, BİL103": her sınıfta BİL103 kodlu iki ders (teori ve
uygulama) varsa o sınıf için bir ilişki önerilir. Öneriler önce ön izlemede gösterilir; kullanıcı
istemediklerinin işaretini kaldırır.
"""

import difflib
import re
from collections import defaultdict
from html.parser import HTMLParser

from django.db import transaction

from .models import CardRelationship as R

IMPORTANCE = {"strict": R.STRICT, "high": R.HIGH, "normal": R.NORMAL, "low": R.LOW}

# Tür metni (sadeleştirilmiş) → (koşul, biçim, varsayılan N)
# biçim: paired = sınıf sınıf eşleşen dersler; together = kapsamdaki tüm eşleşen dersler tek ilişki;
#        set = ders kodları (ders adı) kümesi; ab = A/B tarafları elle seçilmeli
TYPES = {
    # standart
    "takip edemez": (R.AB_NOT_CONSECUTIVE, "ab_same", 1),
    "aynı gün olamaz": (R.DIFFERENT_DAYS, "set", 1),
    "ders kartlarının günlere dağılımı": (R.MAX_PER_DAY, "set", 1),
    "dersler ardarda yerleştirilmelidir (rastgele sırada)": (R.CONSECUTIVE, "paired", 1),
    "dersler ardarda yerleştirilmelidir": (R.CONSECUTIVE_ORDERED, "paired", 1),
    "dersler bir güne yerleştirilmelidir (rastgele sırada)": (R.SAME_DAY, "paired", 1),
    "dersler bir güne yerleştirilmelidir (belirtilen sırayla)": (R.SAME_DAY, "paired", 1),
    "farklı sınıflardaki kart grupları bir güne yerleştirilmelidir": (R.SAME_DAY, "together", 1),
    "bir dersin bölünmüş kartları aynı günde yer almalıdır": (R.MAX_DAYS, "set_lesson", 1),
    "grup olarak tanımlanan dersler aynı zamanda başlasın": (R.SAME_TIME, "together", 1),
    "seçilen derslerin seçilmiş her sınıfla aynı zamanda olması gerekir": (R.SAME_TIME, "together", 1),
    "bu ders her gün aynı periyotta olmalıdır": (R.MAX_DISTINCT_PERIODS, "set_lesson", 1),
    "seçilen dersler için rezerv alanı": (R.RESERVE, "set", 1),
    "dersler ilk saatte başlasın veya son saatte bitsin": (R.FIRST_OR_LAST, "set", 1),
    # gelişmiş
    "kartlar seçilen saatlerde olmalıdır": (R.ONLY_IN_MAP, "set", 1),
    "bir periyot içinde, seçilen değerden az kart olamaz": (R.MIN_PER_POSITION, "set", 1),
    "bir periyot içinde, seçilen değerden fazla kart sayısı olamaz": (R.MAX_PER_POSITION, "set", 1),
    "haftalık ders günü sayısı seçilen değerden az olamaz": (R.MIN_DAYS, "set", 1),
    "haftalık ders günü sayısı seçilen değerden fazla olamaz": (R.MAX_DAYS, "set", 1),
    "günlük ders sayısı seçilen değerden az olamaz (boş günler dikkate alınmaz)": (R.MAP_MIN_IF_ANY, "set", 1),
    "günlük ders sayısı seçilen değerden az olamaz": (R.MIN_PER_DAY, "set", 1),
    "günlük ders sayısı seçilen değerden fazla olamaz": (R.RANGE_MAX_PER_DAY, "set", 1),
    "bir haftada seçilen değerden az ders olamaz": (R.MAP_MIN_WEEK, "set", 1),
    "bir haftada seçilen değerden fazla ders olamaz": (R.MAP_MAX_WEEK, "set", 1),
    "günlük zaman harcaması (boş ve dolu ders toplamı) seçilen değerden az olamaz (boş günler dikkate alınmaz)": (R.DAY_SPAN_MIN, "set", 1),
    "günlük zaman harcaması (boş ve dolu ders toplamı) seçilen değerden fazla olamaz": (R.DAY_SPAN_MAX, "set", 1),
    "hafta içindeki kartlar arasında maksimum serbestliğe sahip günler seçilen değerden fazla olamaz": (R.MAX_FREE_DAYS, "set", 1),
    "günlük boş ders sayısı seçilen değerden fazla olamaz": (R.MAX_GAPS_PER_DAY, "set", 1),
    "haftalık boş ders sayısı seçilen değerden fazla olamaz": (R.MAX_GAPS_WEEK, "set", 1),
    "günlük boş ders sayısı (boş dersler 1 saatten itibaren sayılsın)": (R.GAPS_FROM_START, "set", 1),
    "günlük boş ders sayısı (boş dersler son saatte kadar sayılsın)": (R.GAPS_TO_END, "set", 1),
    "haftalık boş ders sayısı (ilk dersten önce boş ders var ise onlarda boşluk olarak sayılsın)": (R.GAPS_WEEK_FROM_START, "set", 1),
    "haftalık boş ders sayısı (son dersten önce boş ders var ise onlarda boşluk olarak sayılsın)": (R.GAPS_WEEK_TO_END, "set", 1),
    "en fazla ardışık ders günü seçilen değerden fazla olamaz": (R.MAX_CONSEC_DAYS, "set", 1),
    "en fazla ardışık ders sayısı seçilen değerden fazla olamaz": (R.MAX_CONSECUTIVE, "set", 1),
    "en fazla ardışık ders sayısı seçilen değerden fazla olamaz (a&b)": (R.AB_MAX_CONSECUTIVE, "ab", 1),
    "hergün aynı saat için haftalık bazda toplam ders seçilen değerden fazla olamaz": (R.MAX_SAME_PERIOD_DAYS, "set", 1),
    "haftalık en fazla farklı ders sayısı seçilen değerden fazla olamaz": (R.MAX_SUBJECTS_WEEK, "set", 1),
    "bir periyot için, seçilen değerden fazla derslik olamaz": (R.MAX_ROOMS_POSITION, "set", 1),
    "günde en fazla farklı derslik sayısı seçilen değerden fazla olamaz": (R.MAX_ROOMS_DAY, "set", 1),
    "haftalık en fazla farklı derslik sayısı seçilen değerden fazla olamaz": (R.MAX_ROOMS_WEEK, "set", 1),
    "günlük en fazla farklı bina sayısı seçilen değerden fazla olamaz": (R.MAX_BUILDINGS_DAY, "set", 1),
    "max different buildings per week": (R.MAX_BUILDINGS_WEEK, "set", 1),
    "max classroom changes per day": (R.MAX_ROOM_CHANGES, "set", 1),
    "max building changes per day": (R.MAX_BUILDING_CHANGES, "set", 1),
    "günlük en fazla farklı ders sayısı seçilen değerden fazla olamaz": (R.MAX_SUBJECTS_DAY, "set", 1),
    "bir günde en fazla farklı öğretmen sayısı seçilen değerden fazla olamaz": (R.MAX_TEACHERS_DAY, "set", 1),
    "if gap exists, it has to be 2 or more periods long": (R.MIN_GAP_LENGTH, "set", 2),
    "boş ders uzunluğu seçilen değerden fazla olamaz": (R.MAX_GAP_LENGTH, "set", 1),
    "min distance between lessons in one day": (R.MIN_DISTANCE, "set", 1),
    "min free days between lessons (weekend is not considered)": (R.MIN_GAP_DAYS, "set", 1),
    "seçilen iki kayıt aynı saatte olamaz": (R.NOT_SIMULTANEOUS, "set", 1),
    "seçilen iki kayıt aynı gün olamaz": (R.DIFFERENT_DAYS, "set", 1),
    "seçilen sınıfların seçilen dersleri a ve b grubundaki tablolarda ardışık yerleşemez (belirtilen sırayla)": (R.AB_NOT_FOLLOWED, "ab", 1),
    "seçilen sınıfların seçilen dersleri a ve b grubundaki tablolarda ardışık yerleşemez": (R.AB_NOT_CONSECUTIVE, "ab", 1),
    "seçili tablolardaki a pozisyonundaki ders ve sonraki gün b pozisyonunda olamaz": (R.AB_NOT_DAY_AFTER, "ab", 1),
    "seçilen sınıf veya öğretmenlerin dersleri aynı saatte başlamalıdır (a=b)": (R.SAME_TIME, "together", 1),
    "a grubundaki dersler, b grubundaki derslerden sonra olmalıdır (a<b)": (R.AB_AFTER, "ab", 1),
    "a grubundaki dersler, b grubundaki derslerden önce veya sonra olmalıdır": (R.AB_NOT_MIXED, "ab", 1),
    "a grubundaki dersler, b grubundaki derslerden önce olmalıdır": (R.AB_BEFORE, "ab", 1),
    "hafta içinde a dersleri b derslerinden önce olmalıdır": (R.AB_WEEK_BEFORE, "ab", 1),
    "hafta içinde a günü b gününden önce olmalıdır": (R.AB_DAY_BEFORE, "ab", 1),
    "a tablosunda boşluklar, b tablosundaki seçilen kayıtlar ile doldurulmalıdır": (R.AB_FILL_GAPS, "ab", 1),
    "there must be at least one a before b in day": (R.AB_A_FIRST, "ab", 1),
    "there must be at least one b after a in day": (R.AB_B_AFTER, "ab", 1),
    "seçilen saatlerde ders başlayamaz": (R.NO_START_AT, "set", 1),
    "seçilen saatlerde ders bitemez": (R.NO_END_AT, "set", 1),
    "seçilen seçmeli dersin öğrencileri aynı grupta olmalıdır": (R.ST_SAME_GROUP, "set", 1),
    "seçili seçmeli dersin öğrencilerine aynı öğretmen atansın": (R.ST_SAME_TEACHER, "set", 1),
    "öğrenci, bu ders/kurslarda seçilen öğretmenlerden birine sahip olmalıdır": (R.ST_TEACHER_IN, "set", 1),
    "öğrenci, bu ders/kurslarda seçilen öğretmenlerden birine sahip olamaz": (R.ST_TEACHER_NOT_IN, "set", 1),
    "seçilen değerden az seçmeli ders olamaz": (R.ST_MIN_ELECTIVES, "set", 1),
    "seçilen değerden fazla seçmeli ders olamaz": (R.ST_MAX_ELECTIVES, "set", 1),
    "seçilen seçmeli derslerde öğrenci aynı öğretmene sahip olamaz": (R.ST_DIFF_TEACHER, "set", 1),
}
# Haritası olmayan aSc satırında tüm hücrelerle önerilen (ama doğrulanana dek pasif) sayım kuralları.
MAP_ALL = {R.RANGE_MAX_PER_DAY, R.MAP_MIN_WEEK, R.MAP_MAX_WEEK, R.MAP_MIN_IF_ANY, R.MIN_PER_POSITION}
# Gelişmiş kuralların "Uygula" sütunundaki kısaltmaları (ör. a_32): aSc numarası → tür (metin eksikse).
LESSON_LEVEL = {"set_lesson"}


def normalize(text):
    text = (text or "").replace("İ", "i").replace("I", "ı").lower()
    text = re.sub(r"\(#\d+\)", "", text)
    text = re.sub(r"^\s*\d+(\.\d+)?\)\s*", "", text)
    text = re.sub(r"[\*\"“”']", "", text)
    text = text.replace("1. saatten", "1 saatten").rstrip(" .")
    text = re.sub(r"\s*\.\s*\(", " (", text)
    text = re.sub(r"\(\s*", "(", re.sub(r"\s*\)", ")", text))
    return re.sub(r"\s+", " ", text).strip(" .")


_KEYS = {normalize(k): v for k, v in TYPES.items()}


def match_type(text):
    key = normalize(text)
    if key in _KEYS:
        return _KEYS[key]
    close = difflib.get_close_matches(key, _KEYS, n=1, cutoff=0.9)
    return _KEYS[close[0]] if close else None


# --- yapıştırılan metni okuma ------------------------------------------------------------------

class _Rows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.in_cell = [], None, None, False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.row = {"cells": [], "imgs": [], "classes": attrs.get("class", "")}
        elif tag == "td" and self.row is not None:
            self.cell, self.in_cell = [], True
        elif tag == "img" and self.row is not None:
            self.row["imgs"].append(attrs.get("src", ""))

    def handle_endtag(self, tag):
        if tag == "td" and self.row is not None and self.in_cell:
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.in_cell = False
        elif tag == "tr" and self.row is not None:
            if self.row["cells"]:
                self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.in_cell:
            self.cell.append(data)


def parse(text):
    """[{no, scope, type, params, importance, active}] — HTML ya da sekmeli metin."""
    out = []
    if "<tr" in text.lower():
        parser = _Rows()
        parser.feed(text)
        for row in parser.rows:
            cells = row["cells"]
            if len(cells) < 6:
                continue
            imgs = " ".join(row["imgs"])
            m = re.search(r"importance_(strict|high|normal|low)", imgs)
            out.append({
                "no": cells[0], "scope": cells[3], "type": cells[4], "params": cells[5],
                "importance": IMPORTANCE[m[1]] if m else R.STRICT,
                "active": "stop" not in imgs and "item-out" not in row["classes"],
            })
        return out
    for line in text.splitlines():
        cols = [c.strip() for c in line.split("\t")]
        cols = [c for c in cols if c != ""] if len(cols) > 1 else cols
        if len(cols) < 2:
            continue
        if cols[0].isdigit():
            no, cols = cols[0], cols[1:]
        else:
            no = str(len(out) + 1)
        if len(cols) < 2 or normalize(cols[0]) in ("uygula",):
            continue
        out.append({"no": no, "scope": cols[0], "type": cols[1], "params": cols[2] if len(cols) > 2 else "",
                    "importance": R.STRICT, "active": True})
    return out


# --- öneri üretme ------------------------------------------------------------------------------

def _index(school):
    subjects = defaultdict(list)
    for s in school.subjects.all():
        if s.short:
            subjects[s.short.casefold()].append(s)
    classes = {}
    for c in school.classes.all():
        for key in (c.name, c.short):
            if key:
                classes[key.casefold()] = c
    lessons = list(school.lessons.select_related("subject").prefetch_related("classes"))
    return subjects, classes, lessons


def _codes(text, subjects):
    return [t for t in re.split(r"[,\s]+", text or "") if t and t.casefold() in subjects]


def _title(condition):
    return next((t for _, group in R.CONDITION_CHOICES for c, t in group if c == condition), condition).split(" · ")[0]


def plan(school, rows):
    """Satırlardan ilişki önerileri: [{row, name, condition, ... , warning, error}]."""
    subjects, classes, lessons = _index(school)
    days, periods = school.days_per_week, school.periods.count()
    all_cells = [f"{d}-{p}" for d in range(days) for p in range(periods)]
    proposals, seen = [], set()
    existing = {
        (r.condition, tuple(sorted(r.lessons.values_list("id", flat=True))), tuple(sorted(r.subjects.values_list("id", flat=True))))
        for r in school.relationships.all()
    }
    for row in rows:
        found = match_type(row["type"])
        base = {"row": row["no"], "source": f"{row['scope']} · {row['type']}" + (f" · {row['params']}" if row["params"] else ""),
                "importance": row["importance"], "active": row["active"], "warning": "", "error": ""}
        if found is None:
            proposals.append({**base, "error": "Bu ilişki türü desteklenmiyor ya da tanınmadı; elle ekleyin."})
            continue
        condition, kind, default_n = found
        scope, _, right = row["scope"].partition(" - ")
        scope = scope.strip()
        codes = _codes(right, subjects) + _codes(row["params"], subjects)
        numbers = [int(t) for t in re.findall(r"(?<![\w])\d+(?![\w])", row["params"] or "")]
        param = numbers[0] if numbers else default_n
        teacher_scope = scope.casefold().startswith("tüm öğretmen")
        scope_classes, unknown = [], []
        if scope and not scope.casefold().startswith("tüm") and not re.fullmatch(r"a_\d+", scope):
            for name in [x.strip() for x in re.split(r",\s+", scope) if x.strip()]:
                (scope_classes.append(classes[name.casefold()]) if name.casefold() in classes else unknown.append(name))
        warning = f"Bulunamayan sınıflar: {', '.join(unknown)}. " if unknown else ""
        param_max = None
        if len(numbers) > 1 and condition in R.SOFT_TARGET and numbers[1] > numbers[0]:
            param_max = numbers[1]  # aSc'de "6 8": tercih 6, zorunlu kalırsa 8
        elif len(numbers) > 1:
            warning += f"aSc parametreleri “{row['params']}”: N={param} alındı, doğrulayın. "
        title = _title(condition)
        common = {**base, "condition": condition, "param": param, "param_max": param_max, "classes": [c.id for c in scope_classes],
                  "teachers": [], "time_map": [], "lessons": [], "subjects": [], "subjects_b": [],
                  "apply_to": R.EACH_TEACHER if teacher_scope else R.EACH_CLASS}
        if condition in MAP_ALL:
            # Liste hangi saatlerin işaretli olduğunu göstermez; "tüm saatler" yalnızca başlangıç önerisidir.
            # Zorunlu bir sayım kuralını yanlış haritayla açmak programı haksız yere ihlalli gösterir.
            common["time_map"] = all_cells
            common["active"] = False
            warning += "aSc listesinde işaretli saatler görünmüyor; tüm saatler işaretlendi. Haritayı aSc'dekiyle karşılaştırıp etkinleştirin. "
        elif condition in R.NEEDS_MAP:
            common["active"] = False
            warning += "aSc listesinde saatler görünmüyor: ilişkiyi açıp zaman haritasını işaretleyin, sonra etkinleştirin. "
        if kind == "ab":
            common["active"] = False
            warning += "A ve B taraflarını ilişkiyi açıp seçin, sonra etkinleştirin. "
        code_set = {c.casefold() for c in codes}
        matched = [lesson for lesson in lessons if (lesson.subject.short or "").casefold() in code_set]
        if scope_classes:
            ids = {c.id for c in scope_classes}
            matched = [lesson for lesson in matched if ids & {c.id for c in lesson.classes.all()}]
        if codes and not matched:
            proposals.append({**base, "error": f"{', '.join(dict.fromkeys(codes))} kodlu ders bulunamadı."})
            continue
        if not codes and right.strip():
            proposals.append({**base, "error": f"“{right.strip()}” kodları programda yok."})
            continue

        def add(proposal):
            key = (proposal["condition"], tuple(sorted(proposal["lessons"])), tuple(sorted(proposal["subjects"])),
                   tuple(sorted(proposal["classes"])), proposal["param"])
            if key in seen:
                return
            seen.add(key)
            if key[:3] in existing:
                proposal["error"] = "Aynı ilişki zaten var."
            proposals.append(proposal)

        if kind == "paired":
            # Sınıf sınıf: kodların sırasıyla o sınıfın dersleri (aynı kod tekrarlanıyorsa teori + uygulama gibi).
            by_class = defaultdict(list)
            for lesson in matched:
                for c in lesson.classes.all():
                    if not scope_classes or c in scope_classes:
                        by_class[c].append(lesson)
            order = {code.casefold(): i for i, code in reversed(list(enumerate(codes)))}
            same_code = len(code_set) == 1
            before, candidates = len(proposals), 0
            for cls, items in sorted(by_class.items(), key=lambda kv: kv[0].sort_key):
                items = sorted(dict.fromkeys(items), key=lambda x: (order.get(x.subject.short.casefold(), 99), x.periods_per_week, x.id))
                if len(items) < 2:
                    continue
                # Aynı kod iki kez (teori + uygulama): hangisinin önce geleceği belli olmadığından sırasız.
                cond = R.CONSECUTIVE if same_code and condition == R.CONSECUTIVE_ORDERED else condition
                candidates += 1
                add({**common, "condition": cond, "lessons": [x.id for x in items], "classes": [],
                     "name": f"aSc {row['no']}: {_title(cond)} – {', '.join(dict.fromkeys(codes))} ({cls.short or cls.name})",
                     "warning": warning,
                     "detail": " + ".join(f"{x.subject.name} ({x.periods_per_week} sa)" for x in items)})
            if len(proposals) == before:
                proposals.append({**base, "error": "Önceki bir satırla aynı (tekrar)." if candidates else "Hiçbir sınıfta bu kodlarla eşleşen iki ders yok."})
        elif kind == "together":
            items = sorted(dict.fromkeys(matched), key=lambda x: x.id)
            if len(items) < 2:
                proposals.append({**base, "error": "Eşleşen en az iki ders bulunamadı."})
                continue
            add({**common, "lessons": [x.id for x in items], "classes": [], "name": f"aSc {row['no']}: {title} – {', '.join(dict.fromkeys(codes))}",
                 "warning": warning, "detail": " + ".join(f"{x.subject.short} ({', '.join(c.short or c.name for c in x.classes.all())})" for x in items)})
        else:
            subject_ids = sorted({s.id for code in code_set for s in subjects[code]})
            if kind in LESSON_LEVEL:
                common["apply_to"] = R.EACH_SUBJECT_CLASS
            who = "her öğretmen" if teacher_scope else (", ".join(c.short or c.name for c in scope_classes) or "tüm sınıflar")
            add({**common, "subjects": subject_ids, "subjects_b": subject_ids if kind == "ab_same" else [], "warning": warning,
                 "name": f"aSc {row['no']}: {title}" + (f" – {', '.join(dict.fromkeys(codes))}" if codes else f" – {who}"),
                 "detail": (f"{len(matched)} ders · " if codes else "tüm dersler · ") + who + (f" · N={param}" if condition in R.USES_N else "") + (f", istisna {param_max}" if param_max else "")})
    return proposals


@transaction.atomic
def create(school, proposals):
    made = []
    for p in proposals:
        rel = R.objects.create(
            school=school, name=p["name"][:200], condition=p["condition"], param=p["param"], param_max=p.get("param_max"),
            apply_to=p["apply_to"],
            importance=p["importance"], active=p["active"], time_map=p["time_map"],
        )
        rel.lessons.set(p["lessons"])
        rel.subjects.set(p["subjects"])
        rel.subjects_b.set(p.get("subjects_b", []))
        rel.classes.set(p["classes"])
        made.append(rel)
    return made


# --- ekran -------------------------------------------------------------------------------------

def import_view(request, pk):
    """Kart ilişkilerini aSc'den yapıştır: önce ön izleme, sonra seçilenleri oluştur."""
    from django.contrib import messages
    from django.shortcuts import get_object_or_404, redirect, render

    from .models import School
    from .views import _nav

    school = get_object_or_404(School, pk=pk)
    text = request.POST.get("text", "") if request.method == "POST" else ""
    proposals = plan(school, parse(text)) if text.strip() else []
    if request.method == "POST" and request.POST.get("action") == "import":
        chosen = {int(x) for x in request.POST.getlist("sec") if x.isdigit()}
        selected = [p for i, p in enumerate(proposals) if i in chosen and not p["error"]]
        made = create(school, selected)
        inactive = sum(1 for r in made if not r.active)
        messages.success(request, f"{len(made)} kart ilişkisi oluşturuldu." + (
            f" {inactive} tanesi zaman haritası ya da A/B tarafı beklediği için devre dışı; listeden açıp tamamlayın." if inactive else ""))
        return redirect("timetable:data_list", pk=school.pk, slug="kart-iliskileri")
    rows = parse(text) if text.strip() else []
    labels = dict(R.IMPORTANCE_CHOICES)
    for p in proposals:
        p["importance_label"] = labels.get(p["importance"], "")
    return render(request, "timetable/relationship_import.html", {
        **_nav(school, "data"), "data_nav": "kart-iliskileri", "text": text, "rows": rows,
        "proposals": list(enumerate(proposals)), "ok_count": sum(1 for p in proposals if not p["error"]),
    })
