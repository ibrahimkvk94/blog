"""Bölüm veri girişi: bölüm sorumlusu, bölümünün ders adları için hangi öğretmenin kaç kısım okutacağını (sınıf seçmeden)
ve öğretmenlerin mazeretlerini girer, onaya gönderir. Program sorumlusu önerileri karşılaştırmalı görüp onaylar.

Onaylanan dağılım öğretmen havuzu kotalarına (TeacherQuota) yazılır; üretimde kısımların öğretmenini çözücü seçer.
İsteğe bağlı ön dağıtım (bulk_assign.distribute) kısımlara hemen öğretmen yazar. Mazeretler öğretmenin müsaitlik
isteği olarak (AvailabilityRequest) gider ve "Öğretmen istekleri" ekranında onaylanır.
"""

import re
from collections import Counter, defaultdict

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import access, bulk_assign
from . import teacher_requests as tr
from .models import Department, DepartmentSubmission as DS, Lesson, Membership, School, Subject, Teacher, TeacherQuota
from .textsort import natural_key

PREFIX = re.compile(r"^([A-ZÇĞİÖŞÜ]{2,4})\d")


def subject_prefix(subject):
    m = PREFIX.match((subject.short or "").strip().upper())
    return m.group(1) if m else ""


def teacher_prefix(teacher, taught):
    """Öğretmenin bölüm kodu: bölüm alanı, kısa adın ilk sözcüğü ("SVN Ad SOYAD") ya da en çok okuttuğu ders kodu."""
    if teacher.department:
        return teacher.department.strip().upper()
    first = (teacher.short or "").split(" ")[0].upper()
    if 2 <= len(first) <= 4 and first.isalpha() and first != (teacher.short or "").upper():
        return first
    common = taught.get(teacher.id)
    return common.most_common(1)[0][0] if common else ""


def suggestions(school):
    """Ders kodu öneklerine göre önerilen bölümler: [{"name", "subjects": [...], "teachers": [...]}]."""
    subjects = defaultdict(list)
    for s in school.subjects.all():
        if subject_prefix(s):
            subjects[subject_prefix(s)].append(s)
    taught = defaultdict(Counter)
    lesson_subject = dict(Lesson.objects.filter(school=school).values_list("id", "subject_id"))
    by_id = {s.id: s for s in school.subjects.all()}
    for lesson_id, teacher_id in Lesson.teachers.through.objects.filter(lesson__school=school).values_list("lesson_id", "teacher_id"):
        prefix = subject_prefix(by_id[lesson_subject[lesson_id]])
        if prefix:
            taught[teacher_id][prefix] += 1
    teachers = defaultdict(list)
    for t in school.teachers.all():
        teachers[teacher_prefix(t, taught)].append(t)
    existing = {d.name.upper() for d in school.departments.all()}
    return [{"name": p, "subjects": sorted(subjects[p], key=lambda s: natural_key(s.short or s.name)),
             "teachers": sorted(teachers.get(p, []), key=lambda t: natural_key(t.full_name)), "exists": p.upper() in existing}
            for p in sorted(subjects)]


def current(department):
    """Düzenlenen (taslak/bekleyen/reddedilen) öneri; yoksa None."""
    return department.submissions.exclude(status=DS.APPROVED).first()


def subject_rows(department, quotas):
    """Bölüm ders adları: kısım sayısı, saatleri ve öneri satırları."""
    school = department.school
    lessons = defaultdict(list)
    for lesson in Lesson.objects.filter(school=school, subject__in=department.subjects.all()).prefetch_related("classes", "teachers"):
        lessons[lesson.subject_id].append(lesson)
    saved = defaultdict(dict)
    for q in TeacherQuota.objects.filter(school=school, subject__in=department.subjects.all()):
        saved[q.subject_id][q.teacher_id] = q.count
    rows = []
    for subject in sorted(department.subjects.all(), key=lambda s: natural_key(s.short or s.name)):
        sections = bulk_assign.sections(lessons[subject.id])
        hours = sorted({l.periods_per_week for l in sections}) or [0]
        approved = saved.get(subject.id, {})
        if not approved:  # henüz havuz yok: şu anki atamalar
            for l in sections:
                t = bulk_assign._current(l)
                if t:
                    approved[t] = approved.get(t, 0) + 1
        proposal = {int(t): n for t, n in quotas.get(str(subject.id), {}).items()} if str(subject.id) in quotas else dict(approved)
        total = sum(proposal.values())
        rows.append({
            "subject": subject, "sections": len(sections), "hours": hours[0] if len(hours) == 1 else max(hours),
            "mixed_hours": len(hours) > 1, "approved": approved, "proposal": proposal, "total": total,
            "state": "ok" if total == len(sections) and sections else ("over" if total > len(sections) else "under"),
            "changed": proposal != approved,
        })
    return rows


def teacher_loads(department, rows):
    """Öneriye göre öğretmen yükü: bölüm dışı derslerdeki şu anki saat + bu öneriden gelen saat."""
    subjects = {r["subject"].id for r in rows}
    outside = defaultdict(int)
    for lesson in Lesson.objects.filter(school=department.school).exclude(subject_id__in=subjects).prefetch_related("teachers"):
        for t in lesson.teachers.all():
            outside[t.id] += lesson.periods_per_week
    inside = defaultdict(int)
    for r in rows:
        for t, n in r["proposal"].items():
            inside[t] += n * r["hours"]
    return outside, inside


def can_edit(user, department):
    return user.is_superuser or department.users.filter(pk=user.pk).exists() or \
        Membership.DATA in access.school_permissions(user, department.school)


def parse_quotas(post, rows, teacher_ids):
    quotas = {}
    for r in rows:
        sid = r["subject"].id
        found = defaultdict(int)
        for t, n in zip(post.getlist(f"t-{sid}"), post.getlist(f"n-{sid}")):
            if t.isdigit() and int(t) in teacher_ids and n.strip().isdigit() and int(n) > 0:
                found[int(t)] += int(n)
        quotas[str(sid)] = {str(t): n for t, n in found.items()}
    return quotas


def portal(request, pk):
    """Bölüm sorumlusunun ekranı: ders dağılımı ve mazeretler."""
    department = get_object_or_404(Department.objects.select_related("school"), pk=pk)
    if not can_edit(request.user, department):
        raise Http404
    school = department.school
    request.current_school_id = school.pk  # işlem günlüğü bu programa yazsın
    request.current_program_name = school.name
    tab = request.GET.get("sekme") or request.POST.get("sekme") or "dagilim"
    sub = current(department)
    all_teachers = sorted(school.teachers.all(), key=lambda t: natural_key(t.full_name))
    dept_teacher_ids = set(department.teachers.values_list("id", flat=True))
    url = reverse("timetable:department_portal", args=[department.pk])
    if request.method == "POST" and tab == "mazeret":
        teacher = get_object_or_404(Teacher, pk=request.POST.get("ogretmen"), school=school)
        if dept_teacher_ids and teacher.id not in dept_teacher_ids:
            raise Http404  # bölüm yalnızca kendi öğretmenleri için mazeret girer
        reason = (request.POST.get("reason") or "").strip()[:2000]
        req, message = tr.submit(teacher, request.user, tr.parse_cells(request.POST, teacher), reason)
        (messages.success if req else messages.info)(request, message.replace("İsteğiniz", f"{teacher.full_name} için istek"))
        return redirect(f"{url}?sekme=mazeret&ogretmen={teacher.pk}")
    if request.method == "POST" and request.POST.get("action") == "new_teacher":
        return _new_teacher(request, department, sub)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "withdraw" and sub and sub.status == DS.PENDING:
            sub.status = DS.DRAFT
            sub.save(update_fields=["status", "updated_at"])
            messages.info(request, "Öneri geri çekildi; düzenleyip yeniden gönderebilirsiniz.")
            return redirect(url)
        if sub and sub.status == DS.PENDING:
            messages.warning(request, "Öneri onay bekliyor; değiştirmek için önce geri çekin.")
            return redirect(url)
        rows = subject_rows(department, {})
        quotas = parse_quotas(request.POST, rows, {t.id for t in all_teachers})
        if sub is None:
            sub = DS(department=department)
        sub.quotas, sub.message, sub.updated_by = quotas, (request.POST.get("message") or "").strip()[:2000], request.user
        if action == "submit":
            sub.status, sub.submitted_at = DS.PENDING, timezone.now()
            messages.success(request, "Öneri program sorumlusuna gönderildi.")
        else:
            sub.status = DS.DRAFT
            messages.success(request, "Taslak kaydedildi.")
        sub.save()
        return redirect(url)
    context = {"department": department, "dept_school": school, "tab": tab, "sub": sub, "nav": "bolum",
               "last": department.submissions.filter(status=DS.APPROVED).first()}
    if tab == "mazeret":
        people = [t for t in all_teachers if t.id in dept_teacher_ids] or all_teachers
        teacher = next((t for t in people if str(t.pk) == request.GET.get("ogretmen")), people[0] if people else None)
        if teacher is not None:
            pending = tr.pending_of(teacher)
            context.update(teacher=teacher, people=people, grid=tr.grid(teacher, tr.desired_with_pending(teacher)),
                           pending=pending, pending_items=tr.describe(pending) if pending else [])
        return render(request, "timetable/department_portal.html", context)
    rows = subject_rows(department, sub.quotas if sub else {})
    outside, inside = teacher_loads(department, rows)
    names = {t.id: t for t in all_teachers}
    involved = dept_teacher_ids | {t for r in rows for t in r["proposal"]}
    loads = sorted(({"t": names[t], "inside": inside.get(t, 0), "outside": outside.get(t, 0),
                     "total": inside.get(t, 0) + outside.get(t, 0), "target": names[t].target_periods}
                    for t in involved if t in names), key=lambda x: natural_key(x["t"].full_name))
    context.update(new_teachers=list(sub.new_teachers.all()) if sub else [])
    options = teacher_options(department, all_teachers)
    group_of = {o["id"]: o["group"] for o in options}
    for item in loads:
        item["group"] = "" if group_of.get(item["t"].id, "").startswith("Bu bölüm") else group_of.get(item["t"].id, "")
    context.update(options=options)
    context.update(rows=rows, loads=loads, editable=not (sub and sub.status == DS.PENDING),
                   problems=sum(1 for r in rows if r["state"] != "ok"))
    return render(request, "timetable/department_portal.html", context)


def teacher_options(department, teachers):
    """Seçim listesi: önce bu bölümün öğretmenleri, sonra diğer bölümler kendi adlarıyla, en sonda bölümsüzler.
    Her öğretmenin şu anki haftalık ders yükü (tüm dersler) de verilir."""
    groups = defaultdict(list)
    for dept in department.school.departments.prefetch_related("teachers"):
        for t in dept.teachers.all():
            groups[t.id].append(dept)
    load = defaultdict(int)
    hours = dict(Lesson.objects.filter(school=department.school).values_list("id", "periods_per_week"))
    for lesson_id, teacher_id in Lesson.teachers.through.objects.filter(lesson__school=department.school).values_list("lesson_id", "teacher_id"):
        load[teacher_id] += hours.get(lesson_id, 0)
    own, others, none = [], [], []
    for t in teachers:
        depts = groups.get(t.id, [])
        item = {"id": t.id, "name": t.full_name, "load": load[t.id], "target": t.target_periods}
        if any(d.pk == department.pk for d in depts):
            own.append({**item, "group": f"Bu bölüm · {department.name}"})
        elif depts:
            others.append({**item, "group": f"{depts[0].name} bölümü"})
        else:
            none.append({**item, "group": "Bölümü tanımsız"})
    others.sort(key=lambda o: (natural_key(o["group"]), natural_key(o["name"])))
    return own + others + none


def _new_teacher(request, department, sub):
    """Bölüm sorumlusu listede olmayan öğretmeni tanımlar: okula ve bölüme eklenir, öneride ayrıca gösterilir."""
    from django.http import JsonResponse

    if sub is not None and sub.status == DS.PENDING:
        return JsonResponse({"ok": False, "message": "Öneri onay bekliyor; önce geri çekin."}, status=400)
    parts = (request.POST.get("name") or "").split()
    if len(parts) < 2:
        return JsonResponse({"ok": False, "message": "Ad ve soyadı birlikte yazın."}, status=400)
    first, last = " ".join(parts[:-1])[:100], parts[-1][:100]
    school = department.school
    teacher = Teacher.objects.filter(school=school, first_name__iexact=first, last_name__iexact=last).first()
    created = teacher is None
    if created:
        teacher = Teacher.objects.create(school=school, first_name=first, last_name=last,
                                         short=(request.POST.get("short") or "").strip()[:60],
                                         email=(request.POST.get("email") or "").strip()[:254] if "@" in (request.POST.get("email") or "") else "")
        if sub is None:
            sub = DS.objects.create(department=department, updated_by=request.user)
        sub.new_teachers.add(teacher)
    department.teachers.add(teacher)
    return JsonResponse({"ok": True, "id": teacher.id, "name": teacher.full_name, "created": created, "load": 0,
                         "group": f"Bu bölüm · {department.name}",
                         "message": f"{teacher.full_name} tanımlandı ve bölüme eklendi." if created
                         else f"{teacher.full_name} zaten kayıtlı; bölüme eklendi."})


def apply(submission, user, distribute=True, reply=""):
    """Öneriyi onaylar: kotaları yazar, istenirse kısımlara ön dağıtım yapar. Dönüş: notlar."""
    department = submission.department
    school = department.school
    notes = []
    lessons = defaultdict(list)
    for lesson in Lesson.objects.filter(school=school, subject__in=department.subjects.all()).prefetch_related("classes", "teachers"):
        lessons[lesson.subject_id].append(lesson)
    valid_teachers = set(school.teachers.values_list("id", flat=True))
    with transaction.atomic():
        for sid, proposal in submission.quotas.items():
            subject = Subject.objects.filter(pk=int(sid), school=school).first()
            if subject is None:
                continue
            quotas = {int(t): n for t, n in proposal.items() if int(t) in valid_teachers and n > 0}
            TeacherQuota.objects.filter(school=school, subject=subject).delete()
            TeacherQuota.objects.bulk_create(TeacherQuota(school=school, subject=subject, teacher_id=t, count=n) for t, n in quotas.items())
            if not distribute or not quotas:
                continue
            try:
                proposed, _ = bulk_assign.distribute(school, lessons[subject.id], quotas)
            except bulk_assign.DistributeError as exc:
                notes.append(f"{subject.short or subject.name}: ön dağıtım yapılamadı ({exc}); kotalar kaydedildi, üretimde dağıtılır.")
                continue
            for lesson in lessons[subject.id]:
                if lesson.id in proposed and bulk_assign._current(lesson) != proposed[lesson.id]:
                    lesson.teachers.set([proposed[lesson.id]])
        submission.status, submission.decided_by, submission.decided_at, submission.reply = DS.APPROVED, user, timezone.now(), reply
        submission.save(update_fields=["status", "decided_by", "decided_at", "reply"])
    return notes


def admin(request, pk):
    """Program sorumlusu: bölümleri tanımlar, sorumlularını atar ve gelen önerileri onaylar."""
    school = get_object_or_404(School, pk=pk)
    from .views import _nav

    url = reverse("timetable:departments", args=[school.pk])
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "suggest":
            chosen = set(request.POST.getlist("oneri"))
            made = 0
            for s in suggestions(school):
                if s["name"] in chosen and not s["exists"]:
                    dept = Department.objects.create(school=school, name=s["name"])
                    dept.subjects.set(s["subjects"])
                    dept.teachers.set(s["teachers"])
                    made += 1
            messages.success(request, f"{made} bölüm oluşturuldu.")
        elif action == "save":
            dept = get_object_or_404(Department, pk=request.POST.get("bolum"), school=school) if request.POST.get("bolum") else \
                Department(school=school)
            dept.name = (request.POST.get("name") or "").strip()[:100] or "Yeni bölüm"
            dept.save()
            dept.subjects.set(school.subjects.filter(pk__in=request.POST.getlist("subjects")))
            dept.teachers.set(school.teachers.filter(pk__in=request.POST.getlist("teachers")))
            users = set(school.teachers.filter(pk__in=request.POST.getlist("heads"), user__isnull=False).values_list("user_id", flat=True))
            dept.users.set(users)
            missing = school.teachers.filter(pk__in=request.POST.getlist("heads"), user__isnull=True)
            if missing:
                messages.warning(request, "Hesabı olmayan sorumlular eklenmedi: " + ", ".join(t.full_name for t in missing)
                                 + ". Önce Öğretmen hesapları ekranından hesap açın.")
            messages.success(request, f"“{dept.name}” kaydedildi.")
            return redirect(f"{url}?bolum={dept.pk}")
        elif action == "delete":
            Department.objects.filter(pk=request.POST.get("bolum"), school=school).delete()
            messages.info(request, "Bölüm silindi.")
        elif action in ("approve", "reject"):
            sub = get_object_or_404(DS, pk=request.POST.get("oneri"), department__school=school, status=DS.PENDING)
            reply = (request.POST.get("reply") or "").strip()[:2000]
            if action == "approve":
                for note in apply(sub, request.user, distribute=request.POST.get("dagit") == "1", reply=reply):
                    messages.warning(request, note)
                messages.success(request, f"{sub.department.name} önerisi onaylandı ve öğretmen havuzuna yazıldı.")
            else:
                sub.status, sub.decided_by, sub.decided_at, sub.reply = DS.REJECTED, request.user, timezone.now(), reply
                sub.save(update_fields=["status", "decided_by", "decided_at", "reply"])
                messages.info(request, f"{sub.department.name} önerisi düzeltilmek üzere geri gönderildi.")
            return redirect(f"{url}?bolum={sub.department_id}")
        return redirect(url)

    departments = list(school.departments.prefetch_related("subjects", "teachers", "users", "users__teacher_profiles"))
    selected = next((d for d in departments if str(d.pk) == request.GET.get("bolum")), None)
    creating = request.GET.get("yeni") == "1"
    review = None
    if selected is not None:
        sub = current(selected)
        if sub and sub.status == DS.PENDING:
            rows = subject_rows(selected, sub.quotas)
            names = {t.id: t.full_name for t in school.teachers.all()}
            review = {"sub": sub, "new_teachers": list(sub.new_teachers.all()), "rows": [{**r, "lines": _diff_lines(r, names)} for r in rows if r["changed"] or r["state"] != "ok"]}
    status = {d.pk: current(d) for d in departments}
    rows = [{"d": d, "sub": status[d.pk], "heads": [u.get_full_name() or u.username for u in d.users.all()]} for d in departments]
    head_ids = {t.id for d in ([selected] if selected else []) for u in d.users.all() for t in u.teacher_profiles.all()}
    return render(request, "timetable/departments.html", _nav(
        school, "bolumler", rows=rows, selected=selected, creating=creating, review=review,
        suggestions=suggestions(school) if not departments or request.GET.get("oneriler") == "1" else None,
        subjects=sorted(school.subjects.all(), key=lambda s: natural_key(s.short or s.name)),
        teachers=sorted(school.teachers.all(), key=lambda t: natural_key(t.full_name)),
        chosen_subjects={s.id for s in selected.subjects.all()} if selected else set(),
        chosen_teachers={t.id for t in selected.teachers.all()} if selected else set(),
        head_ids=head_ids, pending=sum(1 for s in status.values() if s and s.status == DS.PENDING)))


def _diff_lines(row, names):
    teachers = sorted(set(row["approved"]) | set(row["proposal"]), key=lambda t: natural_key(names.get(t, "")))
    return [{"name": names.get(t, f"#{t}"), "before": row["approved"].get(t, 0), "after": row["proposal"].get(t, 0)} for t in teachers]


def pending_count(school_id):
    return DS.objects.filter(department__school_id=school_id, status=DS.PENDING).count()
