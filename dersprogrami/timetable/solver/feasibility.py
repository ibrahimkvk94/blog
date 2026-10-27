"""Üretimden önce veri denetimi (aSc'deki "Test" adımının karşılığı).

Çözücü "çözüm yok" dediğinde nedenini söylemek zordur; bu yüzden kesin imkânsızlıkları
önceden, hangi verinin sorunlu olduğunu söyleyerek yakalarız.
"""

from collections import defaultdict
from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"


@dataclass
class Issue:
    level: str
    code: str
    message: str

    def as_dict(self):
        return {"level": self.level, "code": self.code, "message": self.message}


def _load_per_universe(problem, card_keys):
    load = defaultdict(int)
    for key in card_keys:
        card = problem.cards[key]
        for universe in card.universes:
            load[universe] += card.length
    return max(load.values(), default=0)


def check(problem):
    issues = []
    total_cells = problem.days * problem.periods

    if problem.periods == 0:
        issues.append(Issue(ERROR, "no_periods", "Okulda tanımlı ders saati yok."))
        return issues

    for card in problem.cards:
        label = problem.label("lesson", card.lesson_id)
        if not card.atoms:
            issues.append(Issue(ERROR, "no_class", f"{label}: derse sınıf atanmamış."))
        if not card.universes:
            issues.append(Issue(ERROR, "no_universe", f"{label}: hafta/dönem maskesi hiçbir haftayı kapsamıyor."))
        if card.fixed is not None:
            if card.fixed not in card.starts:
                issues.append(
                    Issue(WARNING, "locked_on_blocked", f"{label}: kilitli kart yasak bir hücrede duruyor.")
                )
        elif not card.starts:
            issues.append(
                Issue(
                    ERROR,
                    "empty_domain",
                    f"{label}: {card.length} saatlik kart için uygun hücre yok "
                    "(öğretmen/sınıf/derslik müsaitliklerinin kesişimi boş).",
                )
            )

    for teacher_id, keys in problem.cards_by("teachers").items():
        load = _load_per_universe(problem, keys)
        free = problem.teacher_available.get(teacher_id, total_cells)
        if load > free:
            issues.append(
                Issue(
                    ERROR,
                    "teacher_overload",
                    f"{problem.label('teacher', teacher_id)}: haftalık {load} saat ders var, "
                    f"ancak yalnızca {free} uygun hücre var.",
                )
            )
        limits = problem.teacher_limits.get(teacher_id)
        if limits and limits.max_periods_per_day is not None:
            cap = limits.max_periods_per_day * problem.days
            if load > cap:
                issues.append(
                    Issue(
                        ERROR,
                        "teacher_daily_cap",
                        f"{problem.label('teacher', teacher_id)}: {load} saat ders, günlük en fazla "
                        f"{limits.max_periods_per_day} sınırıyla en çok {cap} saat sığar.",
                    )
                )

    for atom_id, keys in problem.cards_by("atoms").items():
        load = _load_per_universe(problem, keys)
        free = problem.atom_available.get(atom_id, total_cells)
        if load > free:
            issues.append(
                Issue(
                    ERROR,
                    "class_overload",
                    f"{problem.label('atom', atom_id)}: haftalık {load} saat ders var, "
                    f"ancak yalnızca {free} uygun hücre var.",
                )
            )

    single_room = defaultdict(list)
    for card in problem.cards:
        if len(card.room_options) == 1:
            single_room[card.room_options[0]].append(card.key)
    for room_id, keys in single_room.items():
        load = _load_per_universe(problem, keys)
        free = total_cells - len(problem.room_blocked.get(room_id, ()))
        if load > free:
            issues.append(
                Issue(
                    ERROR,
                    "room_overload",
                    f"{problem.label('room', room_id)}: yalnızca bu derslikte yapılabilen {load} saat ders var, "
                    f"ancak {free} uygun hücre var.",
                )
            )

    per_lesson = defaultdict(int)
    for card in problem.cards:
        per_lesson[card.lesson_id] += 1
    for lesson_id, count in per_lesson.items():
        max_per_day = problem.lesson_max_per_day.get(lesson_id, count)
        if count > max_per_day * problem.days:
            issues.append(
                Issue(
                    ERROR,
                    "lesson_spread",
                    f"{problem.label('lesson', lesson_id)}: {count} kart, günde en fazla {max_per_day} "
                    f"kuralıyla {problem.days} güne sığmaz.",
                )
            )

    teachers_without_lessons = set(problem.teacher_limits) - set(problem.cards_by("teachers"))
    for teacher_id in sorted(teachers_without_lessons):
        issues.append(Issue(WARNING, "idle_teacher", f"{problem.label('teacher', teacher_id)}: hiç dersi yok."))

    return issues


def has_errors(issues):
    return any(issue.level == ERROR for issue in issues)
