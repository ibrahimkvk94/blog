"""Sınav programı sayfaları: dönemler, sınav listesi, oluşturma, sonuç görünümleri, elle düzenleme, gözetmenler,
yazdırma ve Excel."""

import datetime

from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from timetable import printing
from timetable.forms import ChipSelectMultiple, StyledFormMixin
from timetable.models import DAY_NAMES, Classroom, School, SchoolClass, Subject, Teacher

from . import excel as exam_excel
from . import kurallar
from . import services as exams
from . import solver as exams_solver
from .models import DEFAULT_ROLES, GOZETMEN, ROLE_NAMES, ROLE_ORDER, Exam, ExamPeriod, ExamPlacement

VIEWS = [("takvim", "Takvim"), ("siniflar", "Sınıflar"), ("gozetmenler", "Gözetmenler"), ("salonlar", "Salonlar")]


def _nav(school, **extra):
    from timetable.views import _nav as base_nav

    return base_nav(school, "sinavlar", **extra)


def _period(school, period_id):
    return get_object_or_404(ExamPeriod.objects.select_related("school"), pk=period_id, school=school)


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --- formlar ------------------------------------------------------------------------------------

class PeriodForm(StyledFormMixin, forms.ModelForm):
    sessions_text = forms.CharField(label="Oturum saatleri", initial="09:30, 11:00, 13:30, 15:00",
                                    help_text="Virgülle ayırın, ör. 09:30, 11:00, 13:30, 15:00")
    excluded_text = forms.CharField(label="Hariç günler (tatil)", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                                    help_text="Ör. 29.10.2026, 10.11.2026 — virgülle ya da satır satır")
    session_years_text = forms.CharField(
        label="Oturum düzeni (sınıf düzeyi)", required=False,
        help_text="Ör. 2,1,2,1: 1. oturum 2. sınıflar, 2. oturum 1. sınıflar, 3. oturum 2. sınıflar, 4. oturum 1. sınıflar. "
                  "Her oturumda o düzeyin her bölümünden bir sınav olması tercih edilir. Boş = serbest.")
    weekday_list = forms.MultipleChoiceField(label="Sınav günleri", required=False, widget=ChipSelectMultiple(searchable=False),
                                             choices=[(str(i), n) for i, n in enumerate(DAY_NAMES)])

    class Meta:
        model = ExamPeriod
        fields = ["name", "kind", "start_date", "end_date", "exam_minutes", "max_per_day", "proctors_per_room", "duty_roles",
                  "carriers_per_session",
                  "capacity_percent", "default_seats", "time_limit", "use_availability", "rooms", "shared_rooms"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "rooms": ChipSelectMultiple(), "shared_rooms": ChipSelectMultiple()}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rooms"].queryset = Classroom.objects.filter(school=school).order_by("name")
        self.fields["shared_rooms"].queryset = Classroom.objects.filter(school=school).order_by("name")
        self.fields["shared_rooms"].label_from_instance = lambda r: f"{r} ({r.capacity or 'kapasite yok'})"
        self.fields["rooms"].label_from_instance = lambda r: f"{r} ({r.capacity or 'kapasite yok'})"
        self.fields["max_per_day"].widget.attrs.update(min=1, max=8)
        self.fields["carriers_per_session"].required = False  # KAMYOSİS: boş = 2
        self.fields["capacity_percent"].widget.attrs.update(min=5, max=100)
        self.fields["time_limit"].widget.attrs.update(min=5, max=600)
        inst = self.instance
        if inst.pk:
            self.initial.setdefault("sessions_text", ", ".join(inst.session_times))
            self.initial.setdefault("excluded_text", ", ".join(
                datetime.date.fromisoformat(d).strftime("%d.%m.%Y") for d in inst.excluded_dates or []))
            self.initial.setdefault("weekday_list", [str(d) for d in inst.active_weekdays])
            self.initial.setdefault("session_years_text", ",".join(str(y) for y in inst.session_years or []))
        else:
            self.initial.setdefault("weekday_list", ["0", "1", "2", "3", "4"])
        self._style()

    def clean_carriers_per_session(self):
        value = self.cleaned_data.get("carriers_per_session")
        return 2 if value is None else value

    def clean(self):
        data = super().clean()
        start, end = data.get("start_date"), data.get("end_date")
        if start and end:
            if end < start:
                self.add_error("end_date", "Bitiş başlangıçtan önce olamaz.")
            elif (end - start).days > 120:
                self.add_error("end_date", "Sınav dönemi en fazla 120 gün olabilir.")
        sessions = exams.parse_sessions(data.get("sessions_text"))
        if not sessions:
            self.add_error("sessions_text", "En az bir oturum saati girin (ör. 09:30).")
        elif len(sessions) > 10:
            self.add_error("sessions_text", "Günde en fazla 10 oturum olabilir.")
        data["sessions"] = sessions
        data["excluded"] = exams.parse_dates(data.get("excluded_text"))
        years = [p.strip() for p in str(data.get("session_years_text") or "").replace(";", ",").split(",") if p.strip()]
        if any(not y.isdigit() or not 1 <= int(y) <= 9 for y in years):
            self.add_error("session_years_text", "Virgülle ayrılmış sınıf düzeyleri girin (ör. 2,1,2,1).")
        elif sessions and len(years) > len(sessions):
            self.add_error("session_years_text", f"Günde {len(sessions)} oturum var; en fazla {len(sessions)} düzey girin.")
        data["session_years"] = [int(y) for y in years if y.isdigit()]
        if data.get("time_limit") is not None and not 5 <= data["time_limit"] <= 600:
            self.add_error("time_limit", "5 ile 600 saniye arasında olmalı.")
        if data.get("capacity_percent") is not None and not 1 <= data["capacity_percent"] <= 100:
            self.add_error("capacity_percent", "1 ile 100 arasında olmalı.")
        if data.get("max_per_day") is not None and data["max_per_day"] < 1:
            self.add_error("max_per_day", "En az 1 olmalı.")
        return data

    def save(self, commit=True):
        inst = super().save(commit=False)
        inst.sessions = self.cleaned_data["sessions"]
        inst.excluded_dates = self.cleaned_data["excluded"]
        inst.session_years = self.cleaned_data.get("session_years", [])
        days = sorted({int(d) for d in self.cleaned_data.get("weekday_list") or []})
        inst.weekdays = [] if days == [0, 1, 2, 3, 4] else days
        if commit:
            inst.save()
            self.save_m2m()
        return inst


class ExamForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Exam
        fields = ["name", "classes", "teachers", "duration", "student_count", "count_manual", "fixed_date", "fixed_session",
                  "rooms_needed", "allowed_rooms", "excluded", "note"]
        widgets = {"classes": ChipSelectMultiple(), "teachers": ChipSelectMultiple(), "allowed_rooms": ChipSelectMultiple()}

    def __init__(self, *args, period=None, **kwargs):
        super().__init__(*args, **kwargs)
        school = period.school
        self.fields["classes"].queryset = SchoolClass.objects.filter(school=school)
        self.fields["teachers"].queryset = Teacher.objects.filter(school=school)
        self.fields["teachers"].label_from_instance = lambda t: t.full_name
        self.fields["allowed_rooms"].queryset = Classroom.objects.filter(school=school).order_by("name")
        self.fields["allowed_rooms"].label_from_instance = lambda r: f"{r} ({exams.exam_capacity(r, period)} kişi)"
        dates = period.dates()
        self.fields["fixed_date"] = forms.TypedChoiceField(
            label="Sabit tarih", required=False, empty_value=None, coerce=datetime.date.fromisoformat,
            choices=[("", "—")] + [(d.isoformat(), f"{d:%d.%m.%Y} {DAY_NAMES[d.weekday()]}") for d in dates])
        self.fields["fixed_session"] = forms.TypedChoiceField(
            label="Sabit oturum", required=False, empty_value=None, coerce=int,
            choices=[("", "— (gün içinde serbest)")] + [(i, f"{i + 1}. oturum ({t})") for i, t in enumerate(period.session_times)])
        if self.instance.fixed_date:
            self.initial["fixed_date"] = self.instance.fixed_date.isoformat()
        self.fields["duration"].widget.attrs.update(min=1, max=len(period.session_times))
        self._style()

    def clean_duration(self):
        value = self.cleaned_data["duration"]
        if value < 1:
            raise forms.ValidationError("En az 1 oturum.")
        return value

    def save(self, commit=True):
        if "student_count" in self.changed_data:
            self.instance.count_manual = True
        return super().save(commit)


# --- modülün giriş sayfası ----------------------------------------------------------------------

def home(request):
    """Sınav Planlama'nın giriş sayfası: modülün açık olduğu programlar ve sınav dönemleri."""
    from django.db.models import Count

    from timetable import modules

    schools = (modules.schools_for(request.user, "sinav").select_related("institution")
               .annotate(n_periods=Count("exam_periods")).order_by("institution__name", "name"))
    groups = {}
    for school in schools:
        groups.setdefault(school.institution, []).append(school)
    latest = {}
    for period in ExamPeriod.objects.filter(school__in=schools).order_by("school_id", "-start_date", "-id"):
        latest.setdefault(period.school_id, period)
    rows = [{"institution": inst, "programs": [{"school": s, "latest": latest.get(s.pk)} for s in items]}
            for inst, items in groups.items()]
    return render(request, "sinav/home.html", {"groups": rows, "nav": "sinav_home"})


# --- dönemler -----------------------------------------------------------------------------------

def period_list(request, pk):
    school = get_object_or_404(School, pk=pk)
    form = PeriodForm(request.POST or None, school=school)
    if request.method == "POST":
        if form.is_valid():
            period = form.save(commit=False)
            period.school = school
            period.save()
            form.save_m2m()
            messages.success(request, f"Sınav dönemi oluşturuldu: {period.name}. Şimdi sınavları derslerden oluşturun.")
            return redirect("sinav:period", pk=school.pk, period_id=period.pk)
        messages.error(request, "Formdaki hataları düzeltin.")
    periods = []
    for period in school.exam_periods.all():
        exams.refresh_stale(period)
        periods.append({"period": period, "exams": period.exams.filter(excluded=False).count(),
                        "placed": ExamPlacement.objects.filter(exam__period=period).count(), "days": len(period.dates())})
    return render(request, "sinav/periods.html", _nav(school, periods=periods, form=form,
                                                                 show_form=bool(request.POST) or not periods))


def period_page(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    tab = request.GET.get("sekme", "sinavlar")
    form = PeriodForm(instance=period, school=school)
    if request.method == "POST":
        action = request.POST.get("action")
        back = reverse("sinav:period", args=[school.pk, period.pk])
        if action == "settings":
            form = PeriodForm(request.POST, instance=period, school=school)
            if form.is_valid():
                form.save()
                messages.success(request, "Sınav dönemi ayarları kaydedildi.")
                return redirect(back + "?sekme=ayarlar")
            messages.error(request, "Formdaki hataları düzeltin.")
            tab = "ayarlar"
        elif action == "delete_period":
            name = period.name
            period.delete()
            messages.success(request, f"Sınav dönemi silindi: {name}")
            return redirect("sinav:periods", pk=school.pk)
        else:
            _exam_list_action(request, period, action)
            return redirect(back + (f"?q={request.POST.get('q')}" if request.POST.get("q") else ""))
    rows = list(period.exams.select_related("subject", "placement").prefetch_related("classes", "teachers", "lessons"))
    # KAMYOSİS: ders kodu grupları, kodun sınav türü ve zorluğu
    info = kurallar.bilgiler(school.institution_id)
    subjects = [{"code": code, "name": name, "lessons": lessons, "uyg": code in info and kurallar.plana_alinmaz(info[code].exam_type),
                 "classes": sorted({c.short or c.name for l in lessons for c in l.classes.all()})}
                for code, name, _s, lessons in exams.course_groups(school)] if tab == "sinavlar" else []
    for row in rows:
        row.placed = hasattr(row, "placement")
        course = info.get(row.code or kurallar.ders_kodu(row.subject))
        row.kod = row.code or kurallar.ders_kodu(row.subject)
        row.tur = course.exam_type if course else ""
        row.zorluk = course.difficulty if course else kurallar.VARSAYILAN_ZORLUK
        row.uyg = kurallar.plana_alinmaz(row.tur)
    return render(request, "sinav/period.html", _nav(
        school, period=period, tab=tab, form=form, rows=rows, subjects=subjects,
        multi_subjects=[s for s in subjects if len(s["lessons"]) > 1 and not s["uyg"]],
        uyg_count=sum(1 for s in subjects if s["uyg"]),
        total_students=sum(r.student_count for r in rows if not r.excluded),
        sessions=list(enumerate(period.session_times)), slots=len(period.slots())))


def _exam_list_action(request, period, action):
    selected = [i for i in (_int(x) for x in request.POST.getlist("sel")) if i]
    if action == "from_lessons":
        replace = request.POST.get("mode") != "add"  # "yeniden oluştur" mevcut sınavları ve yerleşimlerini siler
        n =exams.generate_from_lessons(period, separate=request.POST.getlist("separate"), replace=replace)
        messages.success(request, f"{n} sınav oluşturuldu." if replace else f"{n} yeni sınav eklendi.")
    elif action == "save_rows":
        changed = 0
        for exam in period.exams.filter(pk__in=[_int(x) for x in request.POST.getlist("row")]):
            count = _int(request.POST.get(f"count-{exam.pk}"), exam.student_count)
            duration = max(1, min(len(period.session_times), _int(request.POST.get(f"duration-{exam.pk}"), exam.duration)))
            excluded = request.POST.get(f"excluded-{exam.pk}") == "1"
            if (count, duration, excluded) != (exam.student_count, exam.duration, exam.excluded):
                if count != exam.student_count:
                    exam.count_manual = True
                exam.student_count, exam.duration, exam.excluded = max(0, count), duration, excluded
                exam.save()
                changed += 1
        messages.success(request, f"{changed} sınav güncellendi." if changed else "Değişiklik yok.")
    elif action == "merge":
        kept = exams.merge(period, selected)
        if kept is None:
            messages.error(request, "Birleştirmek için en az iki sınav seçin.")
        else:
            messages.success(request, f"{len(selected)} sınav «{kept.title}» ortak sınavında birleştirildi.")
    elif action == "split":
        total = sum(exams.split(period, i) for i in selected)
        if total:
            messages.success(request, f"Seçilen sınavlar sınıf başına {total} sınava bölündü.")
        else:
            messages.error(request, "Bölmek için birden çok sınıfı olan sınav seçin.")
    elif action in ("exclude", "include"):
        n = period.exams.filter(pk__in=selected).update(excluded=action == "exclude")
        if action == "exclude":
            ExamPlacement.objects.filter(exam__period=period, exam_id__in=selected).delete()
        messages.success(request, f"{n} sınav {'programdan çıkarıldı' if action == 'exclude' else 'programa alındı'}.")
    elif action == "delete":
        n = period.exams.filter(pk__in=selected).count()
        period.exams.filter(pk__in=selected).delete()
        messages.success(request, f"{n} sınav silindi.")
    elif action == "refresh_counts":
        n = exams.refresh_counts(period)
        messages.success(request, f"Öğrenci sayıları yeniden hesaplandı ({n} sınav değişti; elle girilenler korunur).")
    elif action == "add":
        subject = Subject.objects.filter(school=period.school_id, pk=_int(request.POST.get("subject"))).first()
        if subject is None:
            messages.error(request, "Ders adı seçin.")
        else:
            Exam.objects.create(period=period, subject=subject, code=kurallar.ders_kodu(subject))
            messages.success(request, f"«{subject}» sınavı eklendi; sınıflarını ve öğrenci sayısını düzenleyin.")


# --- oluşturma ----------------------------------------------------------------------------------

def solve(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    if request.method != "POST":
        exams.refresh_stale(period)
        return JsonResponse({"status": period.status, "running": period.is_running, "report": period.report})
    if not period.exams.filter(excluded=False).exists():
        messages.error(request, "Önce sınavları oluşturun (Derslerden oluştur).")
        return redirect("sinav:period", pk=school.pk, period_id=period.pk)
    if request.POST.get("time_limit"):
        period.time_limit = max(5, min(600, _int(request.POST.get("time_limit"), period.time_limit)))
        period.save(update_fields=["time_limit"])
    if exams.start(period, request.user):
        if period.is_running:
            messages.info(request, "Sınav programı oluşturuluyor; bitince bildirim gelecek.")
        else:
            level = messages.success if period.status == ExamPeriod.OK else (
                messages.warning if period.status == ExamPeriod.PARTIAL else messages.error)
            level(request, {ExamPeriod.OK: "Sınav programı oluşturuldu.", ExamPeriod.PARTIAL: "Sınav programı kısmen oluşturuldu."}
                  .get(period.status, "Sınav programı oluşturulamadı."))
    else:
        messages.info(request, "Oluşturma zaten sürüyor.")
    return redirect("sinav:results", pk=school.pk, period_id=period.pk)


# --- sonuçlar -----------------------------------------------------------------------------------

def results(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    exams.refresh_stale(period)
    if request.method == "POST":
        action = request.POST.get("action")
        qs = ExamPlacement.objects.filter(exam__period=period)
        if action == "lock_all":
            qs.update(locked=True)
            messages.success(request, "Tüm yerleşimler kilitlendi: yeniden oluşturmada yerleri korunur.")
        elif action == "unlock_all":
            qs.update(locked=False)
            messages.success(request, "Tüm kilitler kaldırıldı.")
        elif action == "clear":
            qs.delete()
            messages.success(request, "Sınav programı temizlendi.")
        return redirect(reverse("sinav:results", args=[school.pk, period.pk]) + f"?gorunum={request.POST.get('gorunum', 'takvim')}")
    view = request.GET.get("gorunum", "takvim")
    if view not in dict(VIEWS):
        view = "takvim"
    rows = exams.placements(period)
    issues = exams.validate(period) if not period.is_running else []
    ctx = {"period": period, "view": view, "views": VIEWS, "issues": issues,
           "errors": [i for i in issues if i["level"] == "error"], "warns": [i for i in issues if i["level"] == "warn"],
           "sessions": period.session_times, "placed": len(rows), "total": period.exams.filter(excluded=False).count(),
           "report": period.report or {}}
    if view == "takvim":
        ctx["calendar"] = exams.calendar(period, rows)
    elif view == "siniflar":
        ctx["classes"] = exams.by_class(period, rows)
    elif view == "gozetmenler":
        ctx["teachers"] = exams.by_teacher(period, rows)
        assigned = {t.pk for t, _items in ctx["teachers"]}
        ctx["idle"] = [t for t in exams.proctor_pool(period) if t.pk not in assigned]
    else:
        ctx["rooms"] = exams.by_room(period, rows)
    return render(request, "sinav/results.html", _nav(school, **ctx))


def exam_edit(request, pk, period_id, exam_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    exam = get_object_or_404(Exam.objects.select_related("subject"), pk=exam_id, period=period)
    placement = ExamPlacement.objects.filter(exam=exam).first()
    form = ExamForm(instance=exam, period=period)
    back = reverse("sinav:edit", args=[school.pk, period.pk, exam.pk])
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save":
            form = ExamForm(request.POST, instance=exam, period=period)
            if form.is_valid():
                form.save()
                messages.success(request, "Sınav kaydedildi.")
                return redirect(back)
            messages.error(request, "Formdaki hataları düzeltin.")
        elif action == "place":
            slot = request.POST.get("slot", "")
            raw_date, _, raw_session = slot.partition("#") if slot else (request.POST.get("date", ""), "", request.POST.get("session"))
            try:
                date = datetime.date.fromisoformat(raw_date)
            except ValueError:
                date = None
            session = _int(raw_session, -1)
            if date is None or not 0 <= session < len(period.session_times):
                messages.error(request, "Tarih ve oturum seçin.")
                return redirect(back)
            room_ids = [i for i in (_int(x) for x in request.POST.getlist("rooms")) if i]
            moved = placement is None or (placement.date, placement.session) != (date, session)
            if placement is None:
                placement = ExamPlacement.objects.create(exam=exam, date=date, session=session)
            else:
                placement.date, placement.session = date, session
                placement.save(update_fields=["date", "session"])
            exams.set_rooms(period, placement, room_ids)
            if moved:
                placement.locked = True
                placement.save(update_fields=["locked"])
            messages.success(request, f"Sınav {exams.slot_label(date, session, period)} oturumuna yerleştirildi"
                             + (" ve kilitlendi." if moved else "."))
            _warn(request, period, exam)
            return redirect(back)
        elif action == "proctors" and placement is not None:
            valid = set(Teacher.objects.filter(school=school).values_list("pk", flat=True))
            for room in placement.rooms.all():
                chosen = {}
                for role in (ROLE_ORDER if period.duty_roles else (GOZETMEN,)):
                    names = [f"proctors-{room.pk}-{role}"] + ([f"proctors-{room.pk}"] if role == GOZETMEN else [])
                    for i in (_int(x) for n in names for x in request.POST.getlist(n)):
                        if i in valid and i not in chosen:
                            chosen[i] = role
                room.proctors.set(list(chosen))
                room.roles = {str(t): r for t, r in chosen.items() if r != GOZETMEN}
                room.save(update_fields=["roles"])
            messages.success(request, "Gözetmenler kaydedildi.")
            _warn(request, period, exam)
            return redirect(back)
        elif action == "auto_proctors" and placement is not None:
            n = exams.auto_proctors(period, placement)
            messages.success(request, f"{n} gözetmen atandı." if n else "Eklenecek müsait gözetmen bulunamadı.")
            return redirect(back)
        elif action == "lock" and placement is not None:
            placement.locked = not placement.locked
            placement.save(update_fields=["locked"])
            messages.success(request, "Yerleşim kilitlendi." if placement.locked else "Kilit kaldırıldı.")
            return redirect(back)
        elif action == "unplace" and placement is not None:
            placement.delete()
            messages.success(request, "Sınav programdan kaldırıldı (yerleşmemiş).")
            return redirect(back)
        elif action == "delete":
            exam.delete()
            messages.success(request, "Sınav silindi.")
            return redirect("sinav:period", pk=school.pk, period_id=period.pk)
    slots = exams.slot_status(period, exam)
    room_rows, teacher_rows = [], []
    if placement is not None:
        busy_rooms, busy_teachers = exams.busy_at(period, placement.date, placement.session, exam.duration, skip_exam=exam.pk)
        chosen = set(placement.rooms.values_list("classroom_id", flat=True))
        for r in exams.exam_rooms(period):
            room_rows.append({"room": r, "cap": exams.exam_capacity(r, period), "on": r.pk in chosen, "busy": busy_rooms.get(r.pk)})
        blocks = exams.proctor_blocks(period)
        soft = exams.proctor_soft(period)
        exempt = set(period.proctor_exempt.values_list("pk", flat=True))
        loads = exams.teacher_loads(period)
        own = set(exam.teachers.values_list("pk", flat=True))
        span = {(placement.date, placement.session + k) for k in range(exam.duration)}
        for t in school.teachers.all():
            notes = []
            if t.pk in own:
                notes.append("dersin öğretmeni")
            if t.pk in busy_teachers:
                notes.append(f"dolu: {busy_teachers[t.pk]}")
            if span & blocks.get(t.pk, set()):
                notes.append("müsait değil")
            elif span & soft.get(t.pk, set()):
                notes.append("mümkünse verilmesin")
            if t.pk in exempt:
                notes.append("muaf")
            teacher_rows.append({"teacher": t, "notes": notes, "load": loads.get(t.pk, 0), "roles": period.roles_of(t.pk),
                                 "bad": any(n.startswith(("dolu", "müsait", "muaf")) for n in notes)})
        teacher_rows.sort(key=lambda r: (r["bad"], "dersin öğretmeni" not in r["notes"], r["load"], r["teacher"].last_name))
    else:
        room_rows = [{"room": r, "cap": exams.exam_capacity(r, period), "on": False, "busy": None} for r in exams.exam_rooms(period)]
    rooms = list(placement.rooms.select_related("classroom").prefetch_related("proctors")) if placement else []
    problem = exams_solver.Problem(0, 0, [], [], [], proctors_per_room=period.proctors_per_room, duty_roles=period.duty_roles,
                                   carriers_per_session=period.carriers_per_session if period.duty_roles else 0)
    for room in rooms:  # KAMYOSİS: salonun görevlileri rol rol (rolsüz dönemde yalnızca gözetmen)
        need = exams_solver.duty_need(problem, room.seats)
        current = {t.pk: (room.role_of(t.pk) if period.duty_roles else GOZETMEN) for t in room.proctors.all()}
        room.groups = [{"role": r, "name": ROLE_NAMES[r], "need": need.get(r, 0),
                        "selected": {t for t, role in current.items() if role == r}}
                       for r in (ROLE_ORDER if period.duty_roles else (GOZETMEN,))]
    return render(request, "sinav/edit.html", _nav(
        school, period=period, exam=exam, form=form, placement=placement, slots=slots, room_rows=room_rows,
        teacher_rows=teacher_rows, issues=exams.validate(period, only=exam.pk) if placement else [], rooms=rooms))


def _warn(request, period, exam):
    for issue in exams.validate(period, only=exam.pk):
        messages.warning(request, issue["text"])


# --- gözetmenler --------------------------------------------------------------------------------

def proctors(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    teachers = list(school.teachers.all())
    if request.method == "POST":
        action = request.POST.get("action")
        back = reverse("sinav:proctors", args=[school.pk, period.pk])
        if action == "duty":  # KAMYOSİS: tek öğretmenin muaflığı ve rolleri, kutuya tıklanınca anında kaydedilir
            teacher = exams.teacher_of(period, _int(request.POST.get("teacher")))
            if teacher is None:
                raise Http404
            if request.POST.get("exempt") == "1":
                period.proctor_exempt.add(teacher)
            else:
                period.proctor_exempt.remove(teacher)
            if period.duty_roles:
                roles = dict(period.proctor_roles or {})
                chosen = "".join(r for r in ROLE_ORDER if r in request.POST.get("roles", ""))
                if chosen == DEFAULT_ROLES:
                    roles.pop(str(teacher.pk), None)
                else:
                    roles[str(teacher.pk)] = chosen
                period.proctor_roles = roles
                period.save(update_fields=["proctor_roles"])
            return JsonResponse({"ok": True, "exempt": request.POST.get("exempt") == "1", "roles": period.roles_of(teacher.pk)})
        if action == "exempt":
            ids = {_int(x) for x in request.POST.getlist("exempt")}
            period.proctor_exempt.set([t for t in teachers if t.pk in ids])
            if period.duty_roles:  # KAMYOSİS: alabileceği görev rolleri
                roles = {}
                for t in teachers:
                    chosen = "".join(r for r in ROLE_ORDER if request.POST.get(f"role-{t.pk}-{r}"))
                    if chosen != DEFAULT_ROLES:
                        roles[str(t.pk)] = chosen
                period.proctor_roles = roles
                period.save(update_fields=["proctor_roles"])
            messages.success(request, f"Muafiyetler kaydedildi ({len(ids - {None})} öğretmen muaf).")
            return redirect(back)
        if action == "blocks":
            teacher = exams.teacher_of(period, _int(request.POST.get("teacher")))
            if teacher is None:
                raise Http404
            valid = {d.isoformat() for d in period.dates()}
            n = len(period.session_times)
            by_day = {}
            for value in request.POST.getlist("block"):
                date, _, sess = value.partition("#")
                if date not in valid:
                    continue
                if not sess:
                    by_day[date] = set(range(n))
                elif sess.isdigit() and int(sess) < n:
                    by_day.setdefault(date, set()).add(int(sess))
            items = []
            for date, chosen in sorted(by_day.items()):
                # tüm oturumları seçilen gün tek kayıt olur
                items += [date] if len(chosen) >= n else [f"{date}#{s}" for s in sorted(chosen)]
            blocks = dict(period.proctor_blocks or {})
            if items:
                blocks[str(teacher.pk)] = items
            else:
                blocks.pop(str(teacher.pk), None)
            period.proctor_blocks = blocks
            period.save(update_fields=["proctor_blocks"])
            messages.success(request, f"{teacher.full_name}: gelemeyeceği oturumlar kaydedildi.")
            return redirect(back + f"?ogretmen={teacher.pk}")
    exempt = set(period.proctor_exempt.values_list("pk", flat=True))
    loads = exams.teacher_loads(period)
    blocks = exams.proctor_blocks(period)
    soft = exams.proctor_soft(period)
    marked = {int(k): v for k, v in (period.proctor_blocks or {}).items()}
    rows = [{"teacher": t, "exempt": t.pk in exempt, "load": loads.get(t.pk, 0), "blocked": len(blocks.get(t.pk, ())),
             "soft": len(soft.get(t.pk, ())), "marked": len(marked.get(t.pk, [])), "roles": period.roles_of(t.pk)}
            for t in teachers]
    selected = exams.teacher_of(period, _int(request.GET.get("ogretmen")))
    grid = None
    if selected is not None:
        mine = set(marked.get(selected.pk, []))
        auto = blocks.get(selected.pk, set())
        maybe = soft.get(selected.pk, set())
        grid = []
        for d in period.dates():
            whole = d.isoformat() in mine
            grid.append({"date": d, "day": DAY_NAMES[d.weekday()], "cells": [
                {"value": f"{d.isoformat()}#{s}", "on": whole or f"{d.isoformat()}#{s}" in mine, "auto": (d, s) in auto,
                 "soft": (d, s) in maybe}
                for s in range(len(period.session_times))]})
    pool = len(teachers) - len(exempt)
    return render(request, "sinav/proctors.html", _nav(
        school, period=period, rows=rows, selected=selected, grid=grid, sessions=period.session_times, pool=pool,
        total=sum(loads.values()), role_names=[(r, ROLE_NAMES[r]) for r in ROLE_ORDER],
        departments=sorted({t.department for t in teachers if t.department})))


# --- KAMYOSİS: görev değişikliği ----------------------------------------------------------------

def duty_changes(request, pk, period_id):
    from . import gorev_degisikligi as gd

    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    back = reverse("sinav:duties", args=[school.pk, period.pk])
    if request.method == "POST":
        anahtar = request.POST.get("gorev", "")
        try:
            if request.POST.get("action") == "swap":
                kayit = gd.takas(period, anahtar, request.POST.get("diger", ""), request.user, request.POST.get("neden"))
            else:
                kayit = gd.baskasina_ver(period, anahtar, _int(request.POST.get("yeni")), request.user,
                                         request.POST.get("neden"))
        except gd.DegisiklikHatasi as e:
            messages.error(request, str(e))
            return redirect(f"{back}?gorev={anahtar}")
        messages.success(request, kayit.summary)
        return redirect(back)
    b = gd.Baglam(period)
    gorevler = [{"anahtar": k, "etiket": f"{t.full_name} · {gd.etiket(r, period)}"
                 + (f" · {ROLE_NAMES.get(rol, rol).lower()}" if rol != GOZETMEN else ""), "teacher": t}
                for k, r, t, rol in b.gorevler()]
    gorevler.sort(key=lambda g: (g["teacher"].last_name, g["teacher"].first_name))
    secili = request.GET.get("gorev", "")
    adaylar = takaslar = None
    sec = None
    if secili:
        try:
            oda, ogretmen, rol = b.bul(secili)
        except gd.DegisiklikHatasi as e:
            messages.error(request, str(e))
        else:
            sec = {"anahtar": secili, "oda": oda, "teacher": ogretmen, "rol": ROLE_NAMES.get(rol, rol),
                   "etiket": gd.etiket(oda, period)}
            adaylar = b.adaylar(secili)
            takaslar = b.takaslar(secili)
            for x in takaslar:
                x["etiket"] = gd.etiket(x["oda"], period)
                x["rol_adi"] = ROLE_NAMES.get(x["rol"], x["rol"])
    return render(request, "sinav/duties.html", _nav(
        school, period=period, gorevler=gorevler, sec=sec, adaylar=adaylar, takaslar=takaslar,
        kayitlar=period.duty_changes.select_related("user")[:100]))


# --- çıktılar -----------------------------------------------------------------------------------

def print_view(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    kind = request.GET.get("tur", "takvim")
    rows = exams.placements(period)
    titles = {"takvim": "Sınav takvimi", "gozetmenler": "Gözetmen listesi", "siniflar": "Sınıfların sınav programı",
              "salonlar": "Salonların sınav programı"}
    if kind not in titles:
        kind = "takvim"
    ctx = {"school": school, "period": period, "kind": kind, "title": titles[kind], "brand": printing.settings_of(school),
           "sessions": period.session_times,
           "info": f"{period.name} · {period.start_date:%d.%m.%Y} – {period.end_date:%d.%m.%Y}"}
    if kind == "takvim":
        ctx["calendar"] = [d for d in exams.calendar(period, rows) if any(d["cells"])]
    elif kind == "gozetmenler":
        ctx["teachers"] = exams.by_teacher(period, rows)
    elif kind == "siniflar":
        ctx["classes"] = exams.by_class(period, rows)
    else:
        ctx["rooms"] = exams.by_room(period, rows)
    return render(request, "sinav/print.html", ctx)


def excel_view(request, pk, period_id):
    school = get_object_or_404(School, pk=pk)
    period = _period(school, period_id)
    response = HttpResponse(exam_excel.build(period),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="sinav-programi-{period.pk}.xlsx"'
    return response
