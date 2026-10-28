"""Öğretmen istek formu sayfaları (teacher_requests.py): öğretmenin "İsteklerim" sayfası ve program
sorumlusunun onay sayfası."""

from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import notify, teacher_requests as tr
from .models import AvailabilityRequest, LeaveRequest, School, Timetable
from .textsort import natural_key, tr_lower
from .views import _nav

R = AvailabilityRequest


def my_requests(request):
    """Öğretmen: kendi kartına bağlı programlarda gelemeyeceği saatleri bildirir."""
    teachers = list(tr.linked_teachers(request.user))
    if not teachers:
        return render(request, "timetable/my_requests.html", {"nav": "my_requests", "teachers": []})
    selected = request.GET.get("ogretmen") or request.POST.get("ogretmen")
    teacher = next((t for t in teachers if str(t.pk) == selected), teachers[0])
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "withdraw":
            req = get_object_or_404(R, pk=request.POST.get("istek"), teacher__user=request.user)
            tr.withdraw(req)
            messages.info(request, "İsteğiniz geri alındı.")
        elif action == "leave":
            fields, error = tr.parse_leave(request.POST, teacher)
            if error:
                messages.error(request, error)
            else:
                req, message = tr.submit_leave(teacher, request.user, fields)
                (messages.success if req else messages.error)(request, message)
            return redirect(f"{request.path}?ogretmen={teacher.pk}#izin")
        elif action == "leave_withdraw":
            req = get_object_or_404(LeaveRequest, pk=request.POST.get("izin"), teacher__user=request.user, status=LeaveRequest.PENDING)
            tr.decide_leave(req, None, LeaveRequest.WITHDRAWN)
            messages.info(request, "İzin bildiriminiz geri alındı.")
            return redirect(f"{request.path}?ogretmen={teacher.pk}#izin")
        else:
            reason = (request.POST.get("reason") or "").strip()[:2000]
            req, message = tr.submit(teacher, request.user, tr.parse_cells(request.POST, teacher), reason)
            (messages.success if req else messages.info)(request, message)
        return redirect(f"{request.path}?ogretmen={teacher.pk}")
    pending = tr.pending_of(teacher)
    history = list(teacher.availability_requests.exclude(status=R.PENDING).select_related("decided_by")[:20])
    return render(request, "timetable/my_requests.html", {
        "nav": "my_requests", "teachers": teachers, "teacher": teacher, "pending": pending,
        "pending_items": tr.describe(pending) if pending else [],
        "grid": tr.grid(teacher, tr.desired_with_pending(teacher)),
        "history": [{"r": r, "items": tr.describe(r)} for r in history],
        "leaves": list(teacher.leave_requests.select_related("decided_by")[:20]),
        "leave_kinds": LeaveRequest.KINDS, "periods": list(teacher.school.periods.all()),
        "today": timezone.localdate(),
    })


def _suggest(teacher, users):
    name = tr_lower(f"{teacher.first_name} {teacher.last_name}".strip())
    return next((u for u in users if name and tr_lower(u.get_full_name().strip()) == name), None)


def teacher_requests(request, pk):
    """Program sorumlusu: bekleyen istekleri onaylar/reddeder; öğretmen kartlarını kullanıcı hesaplarına bağlar."""
    school = get_object_or_404(School, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "link":
            users = {u.pk: u for u in User.objects.filter(memberships__institution_id=school.institution_id)}
            changed = 0
            for teacher in school.teachers.all():
                key = f"hesap-{teacher.pk}"
                if key not in request.POST:
                    continue
                value = request.POST[key]
                user_id = int(value) if value.isdigit() and int(value) in users else None
                if user_id != teacher.user_id:
                    teacher.user_id = user_id
                    teacher.save(update_fields=["user"])
                    changed += 1
            messages.success(request, f"{changed} öğretmenin hesap bağlantısı güncellendi.")
            return redirect(f"{request.path}#hesaplar")
        if action in ("leave_approve", "leave_reject"):
            leave = school.leave_requests.filter(pk=request.POST.get("izin"), status=LeaveRequest.PENDING).select_related("teacher").first()
            if leave is None:
                raise Http404
            note = (request.POST.get("note") or "").strip()[:2000]
            if action == "leave_approve":
                days = tr.approve_leave(leave, request.user, note)
                messages.success(request, f"{leave.teacher.full_name}: {days} gün devamsızlık yazıldı; dersleri Vekâlet ekranında.")
            else:
                tr.decide_leave(leave, request.user, LeaveRequest.REJECTED, note)
                messages.info(request, f"{leave.teacher.full_name} izin bildirimi reddedildi.")
            sent, errors = notify.leave_decision_notice(leave, request.build_absolute_uri(reverse("timetable:my_requests")))
            if sent:
                messages.info(request, f"Öğretmene e-posta gönderildi ({leave.teacher.email}).")
            for error in errors:
                messages.warning(request, f"E-posta gönderilemedi: {error}")
            return redirect(reverse("timetable:teacher_requests", args=[school.pk]) + "#izinler")
        req = school.availability_requests.filter(pk=request.POST.get("istek"), status=R.PENDING).first()
        if req is None:
            raise Http404
        note = (request.POST.get("note") or "").strip()[:2000]
        if action == "approve":
            tr.approve(req, request.user, note)
            messages.success(request, f"{req.teacher.full_name}: {len(req.changes)} saat müsaitliğe yazıldı.")
        elif action == "reject":
            tr.reject(req, request.user, note)
            messages.info(request, f"{req.teacher.full_name} isteği reddedildi.")
        else:
            raise Http404
        sent, errors = notify.request_decision_notice(req, tr.describe(req), request.build_absolute_uri(reverse("timetable:my_requests")))
        if sent:
            messages.info(request, f"Öğretmene e-posta gönderildi ({req.teacher.email}).")
        for error in errors:
            messages.warning(request, f"E-posta gönderilemedi: {error}")
        return redirect("timetable:teacher_requests", pk=school.pk)
    timetable = school.active_timetable or school.timetables.exclude(status__in=[Timetable.FAILED, Timetable.RUNNING]).first()
    pending = [{"r": r, "items": tr.describe(r), "conflicts": tr.conflicts(r, timetable),
                "grid": tr.grid(r.teacher, {**tr.current_states(r.teacher), **{(d, p): s for d, p, s in r.changes}})}
               for r in school.availability_requests.filter(status=R.PENDING).select_related("teacher", "requested_by").order_by("created_at")]
    history = [{"r": r, "items": tr.describe(r)} for r in school.availability_requests.exclude(status=R.PENDING)
               .select_related("teacher", "decided_by", "requested_by")[:30]]
    leaves = [{"r": r, "affected": tr.affected_lessons(r, timetable)}
              for r in school.leave_requests.filter(status=LeaveRequest.PENDING).select_related("teacher", "requested_by").order_by("start_date")]
    leave_history = list(school.leave_requests.exclude(status=LeaveRequest.PENDING).select_related("teacher", "decided_by")[:30])
    users = list(User.objects.filter(Q(memberships__institution_id=school.institution_id)).distinct().order_by("username"))
    teachers = sorted(school.teachers.select_related("user"), key=lambda t: natural_key(f"{t.first_name} {t.last_name}"))
    accounts = [{"t": t, "suggest": None if t.user_id else _suggest(t, users)} for t in teachers]
    return render(request, "timetable/data/teacher_requests.html", _nav(
        school, "data", data_nav="istekler", pending=pending, history=history, users=users, accounts=accounts,
        linked=sum(1 for t in teachers if t.user_id), timetable=timetable, leaves=leaves, leave_history=leave_history,
        pending_total=len(pending) + len(leaves)))


def my_timetable(request):
    """Öğretmen: kendi haftalık programı, yaklaşan izin/vekâletler ve telefon takvimi bağlantısı."""
    from . import teacher_calendar as tc

    teachers = list(tr.linked_teachers(request.user))
    if not teachers:
        return render(request, "timetable/my_timetable.html", {"nav": "my_timetable", "teachers": []})
    selected = request.GET.get("ogretmen") or request.POST.get("ogretmen")
    teacher = next((t for t in teachers if str(t.pk) == selected), teachers[0])
    if request.method == "POST":
        renew = request.POST.get("action") == "renew"
        tc.ensure_token(teacher, renew=renew)
        messages.success(request, "Takvim bağlantısı yenilendi; eski bağlantı artık çalışmaz." if renew else "Takvim bağlantısı oluşturuldu.")
        return redirect(f"{request.path}?ogretmen={teacher.pk}")
    timetable = tc.timetable_for(teacher.school)
    ics_url = ""
    if teacher.calendar_token:
        ics_url = request.build_absolute_uri(reverse("timetable:teacher_ics", args=[teacher.calendar_token]))
    return render(request, "timetable/my_timetable.html", {
        "nav": "my_timetable", "teachers": teachers, "teacher": teacher, "timetable": timetable,
        "grid": tc.week_grid(teacher, timetable), "upcoming": tc.upcoming(teacher),
        "ics_url": ics_url, "webcal_url": ics_url.replace("https://", "webcal://").replace("http://", "webcal://"),
    })


@login_not_required
def teacher_ics(request, token):
    """Telefon takvimi aboneliği (giriş gerektirmez; gizli anahtarla)."""
    from django.http import HttpResponse

    from . import teacher_calendar as tc
    from .models import Teacher

    teacher = Teacher.objects.filter(calendar_token=token).select_related("school").first() if len(token) >= 20 else None
    if teacher is None:
        raise Http404
    response = HttpResponse(tc.ics(teacher), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="ders-programi.ics"'
    return response
