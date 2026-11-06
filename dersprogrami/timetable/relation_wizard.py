"""Teori + uygulama ilişki sihirbazı: aynı kodlu teori ve uygulama (U) derslerini her kısımda eşleştirir ve
"art arda / önce teori / aynı gün / farklı günlerde" ilişkilerini toplu oluşturur, günceller ya da kaldırır.

Eşleştirme: ders adları kısa koda göre (kod yoksa adın "(U)"suz haline göre) gruplanır; uygulama dersi adında
"(U)" ya da "(Uyg.)" eki olandır. Aynı sınıf kümesine verilen bir teori ve bir uygulama dersi bir çifttir.
Var olan ilişki: tam olarak bu iki dersi seçen (başka seçimi olmayan) eşleştirme ilişkisi. Sihirbazın kurduğu
ilişkiler çiftin sınıflarıyla süzülür: seçilen ders ders adını temsil ettiğinden (solver/builder.py) süzgeçsiz bir
ilişki bütün kısımlara yayılırdı; sihirbazda ise her kısmın koşulu ayrı seçilebilir.
"""

import re
from collections import defaultdict

from django.db import transaction

from .models import CardRelationship, Lesson
from .rooms_wizard import PRACTICAL
from .textsort import natural_key

R = CardRelationship
CONDITIONS = [
    (R.CONSECUTIVE, "Art arda (bitişik, sıra serbest)"),
    (R.CONSECUTIVE_ORDERED, "Art arda, önce teori sonra uygulama"),
    (R.SAME_DAY, "Aynı gün (bitişik olması gerekmez)"),
    (R.DIFFERENT_DAYS, "Farklı günlerde"),
]
PAIR_CONDITIONS = {c for c, _ in CONDITIONS}
STRIP_U = re.compile(r"\s*\(\s*u(yg\.?)?\s*\)\s*", re.IGNORECASE)


def _key(subject):
    code = (subject.short or "").strip().upper()
    return code or STRIP_U.sub("", subject.name or "").strip().upper()


def analyze(school):
    """Çiftler ve durumları: {"pairs": [...], "unpaired": [...], "summary": {...}}."""
    lessons = list(Lesson.objects.filter(school=school).select_related("subject").prefetch_related("classes", "teachers"))
    groups = defaultdict(lambda: {"T": [], "U": []})
    for lesson in lessons:
        kind = "U" if PRACTICAL.search(lesson.subject.name or "") else "T"
        classes = frozenset(c.id for c in lesson.classes.all())
        if classes:
            groups[(_key(lesson.subject), classes)][kind].append(lesson)
    # ilişkiler: ders kümesi → ilişkiler
    rels = defaultdict(list)
    for rel in school.relationships.prefetch_related("lessons__classes", "subjects", "classes", "teachers", "lessons_b", "subjects_b"):
        if rel.subjects.all() or rel.lessons_b.all() or rel.subjects_b.all() or rel.teachers.all():
            continue
        lesson_classes = {c.id for l in rel.lessons.all() for c in l.classes.all()}
        if rel.classes.all() and {c.id for c in rel.classes.all()} != lesson_classes:
            continue
        ids = frozenset(l.id for l in rel.lessons.all())
        if len(ids) == 2:
            rels[ids].append(rel)
    pairs, unpaired = [], []
    for (code, _), sides in groups.items():
        if not sides["U"]:
            continue
        if len(sides["T"]) != 1 or len(sides["U"]) != 1:
            for lesson in sides["U"]:
                unpaired.append({"lesson": lesson, "reason": "teorisi bulunamadı" if not sides["T"] else "birden çok aday var"})
            continue
        theory, practical = sides["T"][0], sides["U"][0]
        existing = rels.get(frozenset({theory.id, practical.id}), [])
        paired = [r for r in existing if r.condition in PAIR_CONDITIONS]
        status = "missing" if not existing else "duplicate" if len(existing) > 1 else "ok"
        pairs.append({
            "key": f"{theory.id}-{practical.id}", "code": code, "theory": theory, "practical": practical,
            "classes": ", ".join(sorted((c.short or c.name for c in theory.classes.all()), key=natural_key)),
            "teachers": ", ".join(sorted({t.full_name for l in (theory, practical) for t in l.teachers.all()})),
            "relations": existing, "status": status,
            "condition": existing[0].get_condition_display() if existing else "",
            "condition_key": existing[0].condition if existing else "",
            "unknown": bool(existing) and not paired,
        })
    pairs.sort(key=lambda p: (natural_key(p["code"]), natural_key(p["classes"])))
    unpaired.sort(key=lambda u: natural_key(u["lesson"].subject.short or u["lesson"].subject.name))
    counts = defaultdict(int)
    for p in pairs:
        counts[p["status"]] += 1
    conditions = defaultdict(int)
    for p in pairs:
        if p["condition"]:
            conditions[p["condition"]] += 1
    return {"pairs": pairs, "unpaired": unpaired, "conditions": dict(conditions),
            "summary": {"pairs": len(pairs), "missing": counts["missing"], "ok": counts["ok"], "duplicate": counts["duplicate"],
                        "unpaired": len(unpaired)}}


def apply(school, keys, condition, importance, mode):
    """mode: "create" (yalnızca eksiklere), "update" (eksiklere oluştur, varları bu koşula getir),
    "dedupe" (kopyaları sil, birini bırak), "remove" (çiftin ilişkilerini sil). Dönüş: sayılar."""
    if condition not in PAIR_CONDITIONS:
        raise ValueError("Geçersiz koşul.")
    data = analyze(school)
    chosen = [p for p in data["pairs"] if p["key"] in set(keys)]
    created = updated = removed = 0
    label = dict(CONDITIONS)[condition].split(" (")[0]
    with transaction.atomic():
        for p in chosen:
            existing = p["relations"]
            if mode == "remove":
                for rel in existing:
                    rel.delete()
                    removed += 1
                continue
            if mode in ("dedupe", "update") and len(existing) > 1:
                for rel in existing[1:]:
                    rel.delete()
                    removed += 1
                existing = existing[:1]
            if not existing and mode in ("create", "update"):
                rel = R.objects.create(
                    school=school, name=f"Teori + uygulama: {label} – {p['code']} ({p['classes']})"[:200],
                    condition=condition, importance=importance, apply_to=R.EACH_CLASS, param=1)
                rel.lessons.set([p["theory"], p["practical"]])  # sıralı koşulda önce teori
                rel.classes.set(p["theory"].classes.all())  # yalnızca bu kısım
                created += 1
            elif existing and mode == "update":
                rel = existing[0]
                if (rel.condition, rel.importance) != (condition, importance):
                    rel.condition, rel.importance = condition, importance
                    rel.save(update_fields=["condition", "importance"])
                    updated += 1
    return {"created": created, "updated": updated, "removed": removed}
