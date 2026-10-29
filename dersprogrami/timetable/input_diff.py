"""Üretim girdisinin özeti ve karşılaştırması: "dün bulunuyordu, bugün bulunmuyor; arada ne değişti?"

Her üretimde çözücünün gördüğü veri (kurallar, öğretmen sınırları ve uygun saatleri, sınıf sınırları, dersler ve
kartları, öğretmen havuzları, sabit kartlar, zaman ızgarası) okunur metinler olarak Timetable.inputs'a yazılır.
Program bulunamazsa son başarılı üretimin özetiyle karşılaştırılır; ayrıca o zamandan beri yapılan veri işlemleri
işlem günlüğünden listelenir.
"""

from django.utils import timezone

from .models import AuditLog, Timetable
from .solver.cpsat import STRICT

KIND_TITLES = {
    "grid": "Zaman ızgarası", "rules": "Kesin kurallar", "soft_rules": "Tercih kuralları", "teachers": "Öğretmen sınırları",
    "available": "Öğretmenlerin uygun saatleri", "classes": "Sınıf sınırları", "lessons": "Dersler", "pools": "Öğretmen havuzları",
}
# Günlükte üretimi etkilemeyen işlemler (görüntüleme, rapor, yayın, kart taşıma vb.) karşılaştırmaya alınmaz.
IGNORED_PATHS = ("/api/kart/", "/yazdir", "/rapor", "/excel/", "/asc.xml", "/degisiklikler/", "/hizli-ara/", "/basili-cikti/")


def _limits(limits):
    if limits is None:
        return ""
    parts = [(limits.max_periods_per_day, "günde ≤{} ders"), (limits.min_periods_per_day, "geldiği gün ≥{} ders"),
             (limits.max_gaps_per_day, "günde ≤{} boşluk"), (limits.max_gaps_per_week, "haftada ≤{} boşluk"),
             (limits.max_days_per_week, "haftada ≤{} gün"), (limits.max_consecutive, "art arda ≤{} ders")]
    return ", ".join(fmt.format(v) for v, fmt in parts if v is not None)


def fingerprint(problem):
    """Çözücü girdisinin karşılaştırılabilir özeti: {tür: {ad: açıklama}}."""
    label = problem.label
    out = {k: {} for k in KIND_TITLES}
    out["grid"]["ızgara"] = f"{problem.days} gün × {problem.periods} saat"
    for rel in problem.relationships:
        kind = "rules" if rel.weight is None else "soft_rules"
        key = rel.name
        n = 2
        while key in out[kind]:  # aynı adlı ilişkiler
            key = f"{rel.name} ({n})"
            n += 1
        cells = f", {len(rel.cells)} hücre" if rel.cells is not None else ""
        out[kind][key] = f"{rel.condition} N={rel.param}{cells}, {len(rel.groups)} küme"
    teacher_ids = set(problem.teacher_limits) | set(problem.teacher_available)
    for t in teacher_ids:
        name = label("teacher", t)
        if _limits(problem.teacher_limits.get(t)):
            out["teachers"][name] = _limits(problem.teacher_limits.get(t))
        free = problem.teacher_available.get(t)
        if free is not None:
            out["available"][name] = f"{free} uygun saat"
    for c, (low, high) in problem.class_limits.items():
        if low or high:
            out["classes"][label("class", c)] = f"günde {low or 0}–{high if high is not None else '∞'} ders"
    lessons = {}
    for card in problem.cards:
        row = lessons.setdefault(card.lesson_id, {"lengths": [], "teachers": card.teachers, "starts": 0, "fixed": 0})
        row["lengths"].append(card.length)
        row["starts"] += len(card.starts)
        row["fixed"] += card.fixed is not None
    for lesson_id, row in lessons.items():
        teachers = ", ".join(sorted(label("teacher", t) for t in row["teachers"])) or "havuz/öğretmensiz"
        lengths = "+".join(str(n) for n in sorted(row["lengths"], reverse=True))
        fixed = f", {row['fixed']} sabit kart" if row["fixed"] else ""
        out["lessons"][label("lesson", lesson_id)] = f"{lengths} saat · {teachers} · {row['starts']} olası başlangıç{fixed}"
    for pool in problem.teacher_pools:
        quotas = ", ".join(f"{label('teacher', t)} {n}" for t, n in sorted(pool.quotas.items(), key=lambda kv: label("teacher", kv[0])))
        out["pools"][pool.name] = f"{len(pool.lessons)} kısım: {quotas}"
    return out


def compare(old, new, limit=12):
    """İki özet arasındaki farklar: [{"kind", "title", "added": [...], "removed": [...], "changed": [(ad, eski, yeni)], "total"}]."""
    result = []
    for kind, title in KIND_TITLES.items():
        a, b = old.get(kind, {}), new.get(kind, {})
        added = sorted(set(b) - set(a))
        removed = sorted(set(a) - set(b))
        changed = sorted((k, a[k], b[k]) for k in set(a) & set(b) if a[k] != b[k])
        total = len(added) + len(removed) + len(changed)
        if total:
            result.append({"kind": kind, "title": title, "total": total, "added": [(k, b[k]) for k in added[:limit]],
                           "removed": [(k, a[k]) for k in removed[:limit]], "changed": changed[:limit]})
    return result


CHECK_TITLES = {
    "blocked_cell": "Artık yasak olan saate düşen dersler (müsaitlik / kapalı saat değişmiş)",
    "teacher_clash": "Aynı anda iki derse düşen öğretmenler (öğretmen ataması değişmiş)",
    "atom_clash": "Aynı anda iki derse düşen sınıflar / gruplar",
    "room_clash": "Aynı anda iki derse düşen derslikler",
    "students_clash": "Seçmeli derslerde öğrenci çakışması",
    "unplaced": "O programda karşılığı olmayan (yeni eklenen ya da bölünen) dersler",
    "relationship": "Artık sağlanmayan kart ilişkileri",
    "bad_room": "İzin verilmeyen derslik", "room_blocked": "Kapalı saatte kullanılan derslik",
    "teacher_consecutive": "Öğretmen art arda ders sınırı", "teacher_min": "Öğretmenin günlük en az ders sınırı",
    "teacher_day_gaps": "Öğretmen günlük boşluk sınırı", "teacher_week_gaps": "Öğretmen haftalık boşluk sınırı",
    "class_max": "Sınıf günlük en fazla ders", "class_min": "Sınıf günlük en az ders",
}


CHECK_HINTS = {
    "room_clash": "O gün bu dersler aynı saatte yapılabiliyordu; şimdi aynı dersliğe bağlılar ve derslik aynı anda tek ders alıyor. "
                  "Dersliğin “aynı anda en fazla ders” değerini artırın (ör. spor salonu birden çok kısma yetiyorsa) ya da bu "
                  "dersliği derslerden / ders adının varsayılan dersliklerinden kaldırın (Derslik atama).",
    "blocked_cell": "Bu derslerin öğretmeninin, sınıfının ya da dersliğinin müsaitliği değişmiş; kapatılan saatleri kontrol edin.",
    "teacher_clash": "Bu öğretmenler artık aynı saatteki iki dersin de öğretmeni; ders–öğretmen atamalarını kontrol edin.",
    "unplaced": "Bu dersler o programda yoktu ya da kartları değişti (yeni ders, değişen haftalık saat / kart dağılımı).",
    "relationship": "Bu kart ilişkileri o programdan sonra eklendi ya da değişti.",
}


def recheck(previous):
    """Son başarılı programın yerleşimini BUGÜNKÜ verilerle denetler: o gün geçerli olan yerleşimin bugün takıldığı
    kurallar, arada değişen veriyi gösterir (yedek olmasa da çalışır)."""
    from .services import verify_timetable

    try:
        violations, _ = verify_timetable(previous)
    except Exception as exc:  # eski program bugünkü veriyle kurulamadı
        return {"error": str(exc)[:300]}
    groups = {}
    for v in violations:
        if v.level != "hard":
            continue
        g = groups.setdefault(v.code, {"code": v.code, "title": CHECK_TITLES.get(v.code, v.code), "count": 0, "examples": [],
                                       "hint": CHECK_HINTS.get(v.code, "")})
        g["count"] += 1
        if len(g["examples"]) < 8:
            g["examples"].append(v.message)
    return {"groups": sorted(groups.values(), key=lambda g: -g["count"]), "total": sum(g["count"] for g in groups.values())}


def last_success(timetable):
    """Aynı programın, bu üretimden önceki son başarılı (tamamen yerleşmiş) üretimi; katı mod öncelikli."""
    qs = Timetable.objects.filter(school_id=timetable.school_id, status__in=[Timetable.OK, Timetable.PARTIAL],
                                  finished_at__isnull=False).exclude(pk=timetable.pk).order_by("-finished_at")
    return qs.filter(mode=STRICT, status=Timetable.OK).first() or qs.first()


def since_last_success(timetable, inputs):
    """Rapor bölümü: son başarılı üretim, girdi farkları ve o zamandan beri yapılan veri işlemleri."""
    previous = last_success(timetable)
    if previous is None:
        return None
    operations = [
        {"at": f"{timezone.localtime(e.created_at):%d.%m %H:%M}", "user": e.username, "action": e.action, "detail": e.detail[:300]}
        for e in AuditLog.objects.filter(school_id=timetable.school_id, created_at__gt=previous.finished_at,
                                         created_at__lt=timetable.started_at or timetable.created_at)
        .exclude(action__in=["Üretim başlattı", "Üretimi durdurdu", "Programı yayınladı"]).order_by("created_at")
        if not any(p in e.path for p in IGNORED_PATHS)
    ]
    return {
        "previous": {"id": previous.pk, "name": previous.name, "finished_at": f"{timezone.localtime(previous.finished_at):%d.%m.%Y %H:%M}",
                     "mode": previous.mode, "objective": previous.objective},
        "diff": compare(previous.inputs, inputs) if previous.inputs else None,
        "operations": operations[-60:], "operation_count": len(operations),
        "recheck": recheck(previous),
    }
