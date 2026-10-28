"""Esnek raporlar (aSc 26–28. bölümler): bireysel programlar, çarşaf listeler, ders yükü, boş
derslik/öğretmen listeleri. Tüm seçenekler sorgu parametresidir; böylece ayarlar şablon olarak
kaydedilip (ReportPreset) aynen yeniden açılabilir.
"""

import datetime
from collections import defaultdict

from .grid import KINDS, card_payload, room_names
from .models import Availability

TYPES = {
    "bireysel": "Bireysel programlar (her sınıf/öğretmen/derslik ayrı)",
    "carsaf": "Çarşaf liste (haftalık, tümü tek tabloda)",
    "carsaf_gun": "Günlük çarşaf liste (seçilen gün)",
    "yuk": "Öğretmen ders yükü listesi",
    "sinif_dersleri": "Sınıf ders listesi",
    "bos_derslik": "Boş derslikler (gün × saat)",
    "bos_ogretmen": "Boş öğretmenler (gün × saat)",
    "nobet": "Nöbet çizelgesi",
    "uybs": "ÜYBS aktarım listesi (referanslarla)",
}
ENTITY_TYPES = {"bireysel", "carsaf", "carsaf_gun"}
KIND_LABELS = {"sinif": "Sınıflar", "ogretmen": "Öğretmenler", "derslik": "Derslikler"}
CONTENT = {"ogretmen": "Öğretmen", "sinif": "Sınıf", "derslik": "Derslik", "grup": "Grup", "ref": "ÜYBS ref (sınıf programında)"}
DEFAULTS = {
    "tur": "bireysel", "varlik": "sinif", "gunler": "sutun", "ders_adi": "tam", "renk": "1", "boyut": "normal",
    "yon": "yatay", "sayfa": "1", "saat": "1", "gun": "0", "baslik": "", "alt": "", "hafta": "",
    "vekalet": "1",
    # Çarşaf liste seçenekleri
    "satir": "kisi",      # kisi: kişi/sınıf başına bir satır · ders: öğretmenin her dersi ayrı satır
    "hucre": "tam",       # tam: hücrede ders ve ayrıntılar · kisim: yalnızca kısım (sınıf) adı
    "kisim_ad": "kisa",   # kisa: kısa ad · no: yalnızca numara (70.KISIM → 70, Hazırlık 1 → H1)
    "blok": "1",          # 1: blok ders tek hücre · 0: her saat ayrı hücre
    "sutun_ders": "0", "sutun_kod": "0", "sutun_saat": "0",
    "kunye_yer": "on",    # on: adın önünde · sutun: ayrı sütunlarda (çarşaf liste ve ders yükü)
}
KUNYE = {"bolum": "Bölüm", "rutbe": "Rütbe", "unvan": "Ünvan"}
KUNYE_FIELDS = {"bolum": "department", "rutbe": "rank", "unvan": "title"}
PARAM_KEYS = list(DEFAULTS) + ["icerik", "secim", "kunye"]


def options(params):
    """GET parametrelerinden (QueryDict ya da sözlük) temizlenmiş seçenekler."""
    get = params.get
    getlist = params.getlist if hasattr(params, "getlist") else (lambda k: params.get(k) or [])
    o = {key: (get(key) or default) for key, default in DEFAULTS.items()}
    if o["tur"] not in TYPES:
        o["tur"] = "bireysel"
    if o["varlik"] not in KINDS:
        o["varlik"] = "sinif"
    content = getlist("icerik")
    # Hiç içerik gönderilmemişse görünüme uygun varsayılan: sınıf programında öğretmen + derslik vb.
    o["icerik"] = [c for c in content if c in CONTENT] if "icerik_set" in params or content else default_content(o["varlik"])
    if not get("ders_adi") and o["tur"].startswith("carsaf"):
        o["ders_adi"] = "kisa"
    if "icerik_set" in params:  # form gönderildi: işaretsiz onay kutuları "kapalı" demektir
        o["renk"] = get("renk") or "0"
        o["saat"] = get("saat") or "0"
        o["vekalet"] = get("vekalet") or "0"
        o["blok"] = get("blok") or "0"
        for key in ("sutun_ders", "sutun_kod", "sutun_saat"):
            o[key] = get(key) or "0"
    o["secim"] = [int(x) for x in getlist("secim") if str(x).isdigit()]
    kunye = getlist("kunye")
    o["kunye"] = [k for k in kunye if k in KUNYE] if "icerik_set" in params or kunye else list(KUNYE)
    if o["kunye_yer"] not in ("on", "sutun"):
        o["kunye_yer"] = "on"
    o["imza"] = [line.strip() for line in (o["alt"] or "").replace("\r", "").split("\n") if line.strip()][:3]
    o["sayfa"] = o["sayfa"] if o["sayfa"] in ("1", "2", "4") else "1"
    try:
        o["gun"] = int(o["gun"])
    except ValueError:
        o["gun"] = 0
    try:
        o["hafta_tarih"] = datetime.date.fromisoformat(o["hafta"]) if o["hafta"] else None
    except ValueError:
        o["hafta_tarih"] = None
    if o["hafta_tarih"]:  # haftanın Pazartesi'sine çek
        o["hafta_tarih"] -= datetime.timedelta(days=o["hafta_tarih"].weekday())
    return o


def default_content(kind):
    return {"sinif": ["ogretmen", "derslik"], "ogretmen": ["sinif", "derslik"], "derslik": ["sinif", "ogretmen"]}[kind]


def _class_label(cls, o):
    return cls.number_label() if o.get("kisim_ad") == "no" else (cls.short or cls.name)


def _cell_lines(c, kind, o, ref="", class_names=None):
    """Kart hücresinin satırları: ders adı + seçilen ayrıntılar (satırın kendisi tekrar yazılmaz).
    Derslik ayrı satırdadır. Hücre "yalnızca kısım" ise yalnızca sınıf adları yazılır."""
    classes = ", ".join(class_names[i] for i in c["class_ids"] if i in class_names) if class_names else c["classes"]
    color = c["color"] if o["renk"] == "1" else "#ffffff"
    if o.get("hucre") == "kisim" and kind != "sinif":
        return {"lines": [classes or c["subject"]], "color": color, "title": c["title"], "length": c["length"]}
    lines = [c["subject_name"] if o["ders_adi"] == "tam" else c["subject"]]
    extra = [f"ref {ref}"] if ref else []
    if "ogretmen" in o["icerik"] and kind != "ogretmen" and c["teachers"]:
        extra.append(c["teachers"])
    if "sinif" in o["icerik"] and kind != "sinif" and classes:
        extra.append(classes)
    if "grup" in o["icerik"] and c["groups"]:
        extra.append(c["groups"])
    if extra:
        lines.append(" · ".join(extra))
    if "derslik" in o["icerik"] and kind != "derslik" and c["room"]:
        lines.append(c["room"])
    return {"lines": lines, "color": color, "title": c["title"], "length": c["length"]}


def _entities(school, kind, o):
    objects = list(getattr(school, KINDS[kind]).all())
    if kind == "sinif":
        objects = list(school.classes.select_related("class_teacher", "home_classroom"))
    if o["secim"]:
        objects = [obj for obj in objects if obj.pk in o["secim"]]
    return objects


def _kunye_columns(o):
    """Künye ayrı sütunlarda gösterilecekse seçili alanlar (sıralı), değilse boş."""
    return [k for k in KUNYE if k in o["kunye"]] if o.get("kunye_yer") == "sutun" else []


def _title(obj, kind, o=None):
    if kind == "ogretmen" and o is not None and _kunye_columns(o):
        return obj.full_name  # künye ayrı sütunlarda
    if kind == "ogretmen":
        return obj.label(o["kunye"]) if o is not None else obj.full_name
    if kind == "sinif":
        return _class_label(obj, o) if o is not None else (obj.short or obj.name)
    return str(obj)


def build(timetable, o):
    school = timetable.school
    periods = list(school.periods.all())
    days = school.day_names
    data = {"o": o, "school": school, "timetable": timetable, "periods": periods, "days": days,
            "type_label": TYPES[o["tur"]], "kind_label": KIND_LABELS[o["varlik"]]}
    kind = o["varlik"]
    cards = []
    if o["tur"] in ENTITY_TYPES:
        names = room_names(school)
        cards = [
            card_payload(c, kind, names)
            for c in timetable.cards.filter(day__isnull=False)
            .select_related("lesson__subject", "classroom")
            .prefetch_related("lesson__classes", "lesson__teachers", "lesson__groups")
        ]
    builder = {
        "bireysel": _individual, "carsaf": _sheet, "carsaf_gun": _day_sheet, "yuk": _loads,
        "sinif_dersleri": _class_lessons, "bos_derslik": _free_rooms, "bos_ogretmen": _free_teachers, "nobet": _duties,
        "uybs": _uybs,
    }[o["tur"]]
    data.update(builder(timetable, o, cards, periods, days))
    return data


def _at(cards, d, p):
    return [c for c in cards if c["day"] == d and c["period"] <= p < c["period"] + c["length"]]


def _ref_lookup(timetable, o):
    """(kart, sınıf, gün, saat) → ÜYBS ref; yalnızca sınıf programında "ref" içeriği seçiliyse."""
    if "ref" not in o["icerik"] or o["varlik"] != "sinif":
        return {}
    from . import refs

    by_hour = defaultdict(list)  # (ders, sıra) → [(sınıf, ref)]
    for (lesson_id, class_id, ordinal), value in refs.ref_index(timetable.school).items():
        by_hour[(lesson_id, ordinal)].append((class_id, value))
    lookup = {}
    for lesson_id, hours in refs.lesson_hours(timetable).items():
        for ordinal, (day, period, card) in enumerate(hours, start=1):
            if day is not None:
                for class_id, value in by_hour.get((lesson_id, ordinal), ()):
                    lookup[(card.id, class_id, day, period)] = value
    return lookup


def _individual(timetable, o, cards, periods, days):
    kind = o["varlik"]
    pages = []
    refs_at = _ref_lookup(timetable, o)

    names = _class_names(timetable.school, o)

    def cell(mine, obj, d, p):
        return [_cell_lines(c, kind, o, refs_at.get((c["id"], obj.id, d, p), ""), names) for c in _at(mine, d, p)]

    for obj in _entities(timetable.school, kind, o):
        mine = [c for c in cards if obj.id in c["rows"]]
        if o["gunler"] == "satir":
            rows = [{"head": day, "sub": "", "cells": [cell(mine, obj, d, p.index) for p in periods]}
                    for d, day in enumerate(days)]
        else:
            rows = [
                {
                    "head": f"{p.index + 1}.",
                    "sub": f"{p.start_time:%H:%M}–{p.end_time:%H:%M}" if o["saat"] == "1" and p.start_time and p.end_time else "",
                    "cells": [cell(mine, obj, d, p.index) for d in range(len(days))],
                }
                for p in periods
            ]
        info = []
        if kind == "sinif":
            if obj.short and obj.short != obj.name:
                info.append(obj.name)
            if obj.class_teacher:
                info.append(f"Sınıf öğretmeni: {obj.class_teacher.full_name}")
            if obj.home_classroom:
                info.append(f"Derslik: {obj.home_classroom}")
        info.append(f"Haftalık {sum(c['length'] for c in mine)} saat")
        pages.append({"title": _title(obj, kind, o), "info": info, "rows": rows})
    per = int(o["sayfa"])
    columns = [f"{p.index + 1}." for p in periods] if o["gunler"] == "satir" else days
    return {"pages": [pages[i:i + per] for i in range(0, len(pages), per)], "columns": columns}


def _class_names(school, o):
    return {c.id: _class_label(c, o) for c in school.classes.all()}


def _sheet_cells(mine, kind, o, day_range, periods, names=None):
    cells = []
    merge = o.get("blok", "1") == "1"
    for d in day_range:
        p = 0
        while p < len(periods):
            starting = [c for c in mine if c["day"] == d and c["period"] == p]
            span = max((c["length"] for c in starting), default=1) if merge else 1
            span = min(span, len(periods) - p)
            here = starting if (merge and starting) else _at(mine, d, p)
            cells.append({"cards": [_cell_lines(c, kind, o, class_names=names) for c in here], "span": span, "day_start": p == 0})
            p += span
    return cells


def _sheet_rows(timetable, o, cards, periods, day_range):
    """Çarşaf satırları. Öğretmenlerde "ders" satır kipinde her ders (kodu) ayrı satır; isteğe bağlı ders adı/kodu
    sütunları ve son iki sütunda o dersin ve toplam haftalık saat."""
    kind = o["varlik"]
    names = _class_names(timetable.school, o)
    per_lesson = kind == "ogretmen" and o["satir"] == "ders"
    kunye = _kunye_columns(o) if kind == "ogretmen" else []
    rows = []
    for obj in _entities(timetable.school, kind, o):
        mine = [c for c in cards if obj.id in c["rows"]]
        total = sum(c["length"] for c in mine)
        groups = []
        if per_lesson:
            by_lesson = {}
            for c in sorted(mine, key=lambda c: (c["subject"], c["subject_name"], c["day"], c["period"])):
                # Aynı ders farklı kısımlarda tek satır; aynı kodlu ayrı ders (ör. "… (U)") ayrı satır.
                by_lesson.setdefault(c["subject_id"], []).append(c)
            groups = list(by_lesson.values()) or [[]]
        else:
            groups = [mine]
        for i, group in enumerate(groups):
            subjects = list(dict.fromkeys(c["subject_name"] for c in group))
            codes = list(dict.fromkeys(c["subject"] for c in group))
            pre = [getattr(obj, KUNYE_FIELDS[k]) for k in kunye]
            if o["sutun_ders"] == "1":
                pre.append(", ".join(subjects))
            if o["sutun_kod"] == "1":
                pre.append(", ".join(codes))
            post = []
            if o["sutun_saat"] == "1":
                if per_lesson:
                    post.append(sum(c["length"] for c in group))
                post.append(total if i == 0 else "")
            rows.append({"title": _title(obj, kind, o), "first": i == 0, "pre": pre, "post": post,
                         "cells": _sheet_cells(group, kind, o, day_range, periods, names)})
    pre_headers = [KUNYE[k] for k in kunye] + (["Ders adı"] if o["sutun_ders"] == "1" else []) + (["Ders kodu"] if o["sutun_kod"] == "1" else [])
    post_headers = (["Ders saati"] if o["sutun_saat"] == "1" and per_lesson else []) + (["Toplam"] if o["sutun_saat"] == "1" else [])
    return {"sheet_rows": rows, "pre_headers": pre_headers, "post_headers": post_headers}


def _sheet(timetable, o, cards, periods, days):
    return {**_sheet_rows(timetable, o, cards, periods, range(len(days))), "sheet_days": days}


def _day_sheet(timetable, o, cards, periods, days):
    day = min(max(o["gun"], 0), len(days) - 1)
    return {**_sheet_rows(timetable, o, cards, periods, [day]), "sheet_days": [days[day]]}


def _loads(timetable, o, cards, periods, days):
    school = timetable.school
    by_teacher = defaultdict(list)
    for lesson in school.lessons.select_related("subject").prefetch_related("classes", "teachers", "groups"):
        for t in lesson.teachers.all():
            by_teacher[t.id].append(lesson)
    teachers = list(school.teachers.prefetch_related("subjects"))
    if o["secim"] and o["varlik"] == "ogretmen":
        teachers = [t for t in teachers if t.pk in o["secim"]]
    rows = []
    for t in teachers:
        lessons = sorted(by_teacher.get(t.id, []), key=lambda x: x.subject.name)
        total = sum(x.periods_per_week for x in lessons)
        rows.append({
            "teacher": t, "title": t.label(o["kunye"]), "name": _title(t, "ogretmen", o),
            "kunye": [getattr(t, KUNYE_FIELDS[k]) for k in _kunye_columns(o)], "total": total, "target": t.target_periods,
            "diff": (total - t.target_periods) if t.target_periods else None,
            "lessons": [{
                "subject": x.subject.name, "classes": ", ".join(c.short or c.name for c in x.classes.all()) or "–",
                "groups": ", ".join(sorted({g.name for g in x.groups.all()})), "hours": x.periods_per_week,
                "split": "+".join(str(n) for n in x.card_lengths()),
            } for x in lessons],
        })
    return {"load_rows": rows, "kunye_headers": [KUNYE[k] for k in _kunye_columns(o)]}


def _class_lessons(timetable, o, cards, periods, days):
    school = timetable.school
    classes = list(school.classes.select_related("class_teacher"))
    if o["secim"] and o["varlik"] == "sinif":
        classes = [c for c in classes if c.pk in o["secim"]]
    by_class = defaultdict(list)
    for lesson in school.lessons.select_related("subject").prefetch_related("classes", "teachers", "groups"):
        for c in lesson.classes.all():
            by_class[c.id].append(lesson)
    rows = []
    for cls in classes:
        lessons = sorted(by_class.get(cls.id, []), key=lambda x: x.subject.name)
        rows.append({
            "cls": cls, "title": cls.short or cls.name, "total": sum(x.periods_per_week for x in lessons if not x.groups.exists()),
            "lessons": [{
                "subject": x.subject.name, "teachers": ", ".join(t.full_name for t in x.teachers.all()) or "–",
                "groups": ", ".join(sorted({g.name for g in x.groups.all()})), "hours": x.periods_per_week,
                "split": "+".join(str(n) for n in x.card_lengths()),
            } for x in lessons],
        })
    return {"class_rows": rows}


def _free_matrix(days, periods, names_free):
    return [{"day": day, "cells": [names_free(d, p.index) for p in periods]} for d, day in enumerate(days)]


def _free_rooms(timetable, o, cards, periods, days):
    school = timetable.school
    rooms = list(school.classrooms.all())
    used = defaultdict(int)
    for card in timetable.cards.filter(day__isnull=False):
        for i in range(card.length):
            for r in card.room_ids:
                used[(r, card.day, card.period + i)] += 1
    blocked = set(Availability.objects.filter(school=school, classroom__isnull=False, state=Availability.NO)
                  .values_list("classroom_id", "day", "period"))

    def free(d, p):
        return [str(r) for r in rooms if used[(r.id, d, p)] < r.max_lessons and (r.id, d, p) not in blocked]
    return {"free_rows": _free_matrix(days, periods, free), "free_label": "Boş derslikler"}


def _free_teachers(timetable, o, cards, periods, days):
    school = timetable.school
    teachers = list(school.teachers.all())
    busy = set()
    at_school = defaultdict(set)
    for card in timetable.cards.filter(day__isnull=False).prefetch_related("lesson__teachers"):
        for t in card.lesson.teachers.all():
            at_school[t.id].add(card.day)
            for i in range(card.length):
                busy.add((t.id, card.day, card.period + i))
    blocked = set(Availability.objects.filter(school=school, teacher__isnull=False, state=Availability.NO)
                  .values_list("teacher_id", "day", "period"))

    def free(d, p):
        # Okulda olan (o gün dersi bulunan) boş öğretmenler önce; vekâlet için kullanışlı.
        names = [(d not in at_school[t.id], t.full_name) for t in teachers
                 if (t.id, d, p) not in busy and (t.id, d, p) not in blocked]
        return [(name + ("" if not away else " ·")) for away, name in sorted(names)]
    return {"free_rows": _free_matrix(days, periods, free), "free_label": "Boş öğretmenler",
            "free_note": "“·” işaretli öğretmenlerin o gün dersi yok (okulda olmayabilir)."}


def _duties(timetable, o, cards, periods, days):
    from . import duty

    return {"duty": duty.roster(timetable.school, timetable)}


def selectable(school, kind):
    objs = list(getattr(school, KINDS[kind]).all())
    return [{"id": obj.pk, "name": _title(obj, kind)} for obj in objs]


def _uybs(timetable, o, cards, periods, days):
    from . import uybs

    ids = o["secim"] if o["varlik"] == "sinif" else None
    rows, archive = uybs.week_rows(timetable, o["hafta_tarih"], ids, substitutions=o["vekalet"] == "1")
    return {"uybs_rows": rows, "uybs_missing": sum(1 for r in rows if not r["ref"]), "uybs_archive": archive,
            "uybs_subs": sum(1 for r in rows if r.get("sub"))}
