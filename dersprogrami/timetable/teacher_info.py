"""Öğretmen bilgileri toplu düzenleme: bölüm, ünvan / rütbe, branş ve TC kimlik no.

Bütün öğretmenler tek tabloda düzenlenebilir hücrelerle gelir. Seçilen satırlara aynı bölüm / ünvan / branş tek
seferde yazılabilir; Excel'den kopyalanan "öğretmen ⇥ TC" (ya da başlıklı birden çok sütun) satırları tabloya
yapıştırılır. Bunlar tarayıcıda hücreleri doldurur, değişen hücreler işaretlenir; kayıt "Kaydet" ile yapılır.
"""

import re

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse

from .models import Teacher
from .textsort import natural_key

FIELDS = (("department", "Bölüm"), ("title", "Ünvan / rütbe"), ("branch", "Branş"), ("tc_no", "TC kimlik no"))
LIMITS = {name: Teacher._meta.get_field(name).max_length for name, _ in FIELDS}


def save(school, data):
    """POST verisinden (t-<id>-<alan>) değişen alanları yazar. Dönüş: (değişen öğretmen sayısı, hatalar)."""
    changed, errors, updates = 0, [], []
    for teacher in school.teachers.all():
        fields = []
        for name, label in FIELDS:
            key = f"t-{teacher.pk}-{name}"
            if key not in data:
                continue
            value = " ".join((data.get(key) or "").split())
            if name == "tc_no":
                value = re.sub(r"\D", "", value)
                if value and len(value) != 11:
                    errors.append(f"{teacher.full_name}: TC kimlik no 11 haneli olmalı ({value}).")
                    continue
            value = value[:LIMITS[name]]
            if value != getattr(teacher, name):
                setattr(teacher, name, value)
                fields.append(name)
        if fields:
            updates.append((teacher, fields))
    if errors:
        return 0, errors
    with transaction.atomic():
        for teacher, fields in updates:
            teacher.save(update_fields=fields)
            changed += 1
    return changed, []


def page(request, pk):
    from .data_views import _school
    from .views import _nav

    school = _school(pk)
    if request.method == "POST":
        changed, errors = save(school, request.POST)
        if errors:
            for e in errors[:20]:
                messages.error(request, e)
            if len(errors) > 20:
                messages.error(request, f"… ve {len(errors) - 20} hata daha.")
            messages.warning(request, "Hiçbir değişiklik kaydedilmedi; hatalı satırları düzeltip yeniden deneyin.")
        else:
            messages.success(request, f"{changed} öğretmenin bilgisi güncellendi." if changed else "Değişiklik yok.")
        return redirect(reverse("timetable:teacher_info", args=[school.pk]))
    teachers = sorted(school.teachers.all(), key=lambda t: natural_key(f"{t.first_name} {t.last_name}"))
    suggestions = {name: sorted({getattr(t, name) for t in teachers if getattr(t, name)}, key=natural_key)
                   for name in ("department", "title", "branch")}
    return render(request, "timetable/data/teacher_info.html", _nav(
        school, "data", data_nav="ogretmen-bilgileri", teachers=teachers, suggestions=suggestions,
        missing_tc=sum(1 for t in teachers if not t.tc_no)))
