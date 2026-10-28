"""Bütün okulu arka planda iyileştirme: 10–30 dakika boyunca öğretmenleri (ve sınıfları) en kötüden
başlayarak küçük gruplar halinde ele alır; her adımda çözüm merkezinin iyileştirmesini (resolve.Center.improve)
bellekteki programa uygular. Program veritabanında değişmez: sonuç tek bir öneri olarak saklanır ve
çözüm merkezinde önizlenip uygulanır (geri alınabilir).

Çalışma biçimi üretimle aynıdır: yerel kurulumda web sürecinde ayrı iş parçacığı, sunucu kurulumunda
(TIMETABLE_JOB_BACKEND=worker) `calisan` süreci. İlerleme ve nabız her adımda veritabanına yazılır;
"Durdur" o ana kadar bulunan iyileştirmeyle bitirir.
"""

import math
import threading
import time
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, connection
from django.utils import timezone

from . import jobs
from .models import ImproveJob
from .resolve import Center, ResolveError
from .solver.validate import validate

BATCH = 2            # bir adımda ele alınan öğretmen/sınıf sayısı; komşularıyla birlikte serbest kalan kart
                     # sayısı hızla büyür (büyük okulda 2 öğretmen ≈ 200 kart, 4 öğretmen ≈ okulun yarısı)
MAX_MOVES = 12       # bir adımda en fazla oynatılan ders
STEP_LIMIT = 20      # bir adımın çözüm süresi (sn)
MIN_STEP = 8         # bundan az süre kaldıysa yeni adım başlatılmaz
STALE_AFTER = 180    # nabız bu kadar saniye gelmezse iş yarıda kalmış sayılır
LIMITS = (10, 20, 30)  # dakika seçenekleri
# Adımın kabulü tüm okulun toplamına bakar: okula fazladan gelinen gün bir boş saatten pahalıdır, böylece
# boşluğu azaltırken gün sayısını artıran değişiklikler kolay kabul edilmez.
SCORE = {"teacher_gaps": 40, "teacher_days": 60, "class_gaps": 30}

J = ImproveJob


def start(timetable, user, minutes):
    """İşi başlatır (zaten çalışan varsa onu döndürür)."""
    current = active_job(timetable)
    if current is not None:
        return current
    job = J.objects.create(timetable=timetable, created_by=user if user and user.is_authenticated else None,
                           time_limit=int(minutes) * 60)
    if jobs.worker_mode():
        return job  # calisan süreci sıradan alır
    if not getattr(settings, "TIMETABLE_RUN_IN_BACKGROUND", True):
        run(job.pk)
        return job
    threading.Thread(target=_thread, args=(job.pk,), daemon=True, name=f"improve-{job.pk}").start()
    return job


def _thread(job_id):
    close_old_connections()
    try:
        run(job_id)
    finally:
        connection.close()


def claim_next():
    """Çalışan süreç için: sıradaki işi atomik olarak alır."""
    for job in J.objects.filter(status=J.QUEUED).order_by("created_at")[:5]:
        if J.objects.filter(pk=job.pk, status=J.QUEUED).update(status=J.RUNNING, heartbeat=timezone.now()):
            return J.objects.get(pk=job.pk)
    return None


def active_job(timetable):
    job = timetable.improve_jobs.filter(status__in=[J.QUEUED, J.RUNNING]).first()
    return refresh_stale(job) if job else None


def refresh_stale(job):
    """Sunucu yeniden başlarsa yarıda kalan işi "başarısız" yapar. Dönüş: hâlâ etkinse iş, değilse None."""
    if job.status == J.RUNNING and job.heartbeat and timezone.now() - job.heartbeat > timedelta(seconds=STALE_AFTER):
        J.objects.filter(pk=job.pk).update(status=J.FAILED, finished_at=timezone.now(),
                                           error="İş yarıda kesildi (sunucu yeniden başlatılmış olabilir).")
        job.refresh_from_db()
    return job if job.active else None


def request_stop(job):
    if job.status == J.QUEUED:
        J.objects.filter(pk=job.pk, status=J.QUEUED).update(status=J.CANCELLED, finished_at=timezone.now())
    else:
        J.objects.filter(pk=job.pk).update(stop_requested=True)


# --- iyileştirme döngüsü ---------------------------------------------------------------------------

def _owner_stats(full, placements):
    """{("t", id) | ("c", id): (boşluk, gün, ders saati)}"""
    busy = defaultdict(lambda: defaultdict(set))
    for card in full.cards:
        place = placements.get(card.key)
        if place is None:
            continue
        cells = range(place.period, place.period + card.length)
        for t in card.teachers:
            busy[("t", t)][place.day].update(cells)
        for c in {full.atom_class(a) for a in card.atoms}:
            busy[("c", c)][place.day].update(cells)
    return {o: (sum(max(p) - min(p) + 1 - len(p) for p in days.values() if p),
                sum(1 for p in days.values() if p), sum(len(p) for p in days.values()))
            for o, days in busy.items()}


def _candidates(full, placements, kind, periods, skip):
    """İyileştirme payı olanlar, en kötüden: boşluğu olanlar ve gerekenden fazla gün gelen öğretmenler."""
    rows = []
    for (k, owner), (gaps, days, hours) in _owner_stats(full, placements).items():
        if k != kind or owner in skip:
            continue
        extra_days = max(0, days - math.ceil(hours / max(1, periods))) if kind == "t" else 0
        if gaps or extra_days:
            rows.append((-(gaps * 4 + extra_days * 3), owner))
    return [owner for _, owner in sorted(rows)]


def _totals(full, placements):
    stats = _owner_stats(full, placements)
    return {key: sum(v[i] for (k, _), v in stats.items() if k == kind)
            for key, kind, i in (("teacher_gaps", "t", 0), ("teacher_days", "t", 1), ("class_gaps", "c", 0))}


def _score(totals):
    return sum(SCORE[k] * totals[k] for k in SCORE)


def run(job_id):
    job = J.objects.select_related("timetable__school").get(pk=job_id)
    if job.status == J.CANCELLED:
        return
    now = timezone.now()
    J.objects.filter(pk=job.pk).update(status=J.RUNNING, started_at=now, heartbeat=now)
    began = time.monotonic()
    deadline = began + job.time_limit
    progress = {"phase": "Program yükleniyor", "limit": job.time_limit, "elapsed": 0, "step": 0, "accepted": 0, "moves": 0}

    def beat(**changes):
        progress.update(changes, elapsed=int(time.monotonic() - began))
        J.objects.filter(pk=job.pk).update(progress=dict(progress), heartbeat=timezone.now())
        return J.objects.filter(pk=job.pk).values_list("stop_requested", flat=True).first()

    try:
        center = Center(job.timetable)
        full, original = center.full, dict(center.placements)
        baseline_v, baseline_stats = validate(full, original)
        start_totals = _totals(full, original)
        periods = len(job.timetable.school.periods.all())
        progress.update(before=start_totals, now=start_totals)
        names = {**{("t", t.id): t.full_name for t in job.timetable.school.teachers.all()},
                 **{("c", c.id): c.short or c.name for c in job.timetable.school.classes.all()}}
        stopped = beat(phase="Öğretmenler")
        tried = set()  # bu turda sonuçsuz denenenler
        kind, round_no, round_gain = "t", 1, False
        while not stopped and deadline - time.monotonic() >= MIN_STEP:
            queue = _candidates(full, center.placements, kind, periods, tried)
            if not queue:
                # Tur bitti: öğretmenlerden sınıflara, sınıflardan yeni tura; ilerleme yoksa erken bitir
                if kind == "t":
                    kind, tried = "c", set()
                    stopped = beat(phase="Sınıflar")
                    continue
                if not round_gain:
                    break
                kind, tried, round_no, round_gain = "t", set(), round_no + 1, False
                stopped = beat(phase=f"Öğretmenler ({round_no}. tur)")
                continue
            batch = queue[:BATCH]
            tried.update(batch)
            stopped = beat(step=progress["step"] + 1, current=", ".join(names.get((kind, o), "?") for o in batch))
            if stopped:
                break
            limit = min(STEP_LIMIT, max(MIN_STEP, deadline - time.monotonic()))
            try:
                proposal = center.improve(teacher_ids=batch if kind == "t" else (),
                                          class_ids=batch if kind == "c" else (), max_moves=MAX_MOVES, time_limit=limit,
                                          weights=(SCORE["teacher_gaps"], SCORE["teacher_days"]), everyone=True)
            except ResolveError:
                proposal = None
            if proposal:
                after = _totals(full, center.last_after)
                if _score(after) < _score(progress["now"]):
                    center.placements = center.last_after
                    round_gain = True
                    moved = sum(1 for k, p in center.placements.items()
                                if original.get(k) is None or (original[k].day, original[k].period) != (p.day, p.period))
                    stopped = beat(accepted=progress["accepted"] + 1, moves=moved, now=after)
        final = center.placements
        moved_keys = {k for k, p in final.items() if original.get(k) is None or (original[k].day, original[k].period) != (p.day, p.period)}
        result = None
        if moved_keys or any(original.get(k) and p.rooms != original[k].rooms for k, p in final.items()):
            center.placements = original
            result = center._report(final, moved_keys, baseline_v, baseline_stats)
            if result["new_violations_hard"]:  # her adım denetlendiği için beklenmez; yine de uygulanmasın
                raise ResolveError("İyileştirme yeni kural ihlali üretti; sonuç kullanılmadı.")
            all_t = {o for (k, o) in _owner_stats(full, original) if k == "t"}
            all_c = {o for (k, o) in _owner_stats(full, original) if k == "c"}
            result["quality"] = center._quality_change(original, final, all_t, all_c)
            result["totals"] = {"before": start_totals, "after": _totals(full, final)}
        progress.update(phase="Bitti", current="", elapsed=int(time.monotonic() - began))
        J.objects.filter(pk=job.pk).update(status=J.DONE, result=result, progress=progress, finished_at=timezone.now(),
                                           heartbeat=timezone.now())
    except Exception as exc:  # iş "çalışıyor" durumunda asılı kalmasın
        J.objects.filter(pk=job.pk).update(status=J.FAILED, error=str(exc)[:2000], finished_at=timezone.now())
        if not isinstance(exc, ResolveError):
            raise


# --- ekran ---------------------------------------------------------------------------------------

LABEL = "Okul geneli iyileştirme"


def _state(job):
    if job is None:
        return None
    return {"id": job.pk, "status": job.status, "label": job.get_status_display(), "progress": job.progress,
            "error": job.error, "stop_requested": job.stop_requested, "has_result": bool(job.result)}


def improve_view(request, pk):
    from django.contrib import messages
    from django.http import JsonResponse
    from django.shortcuts import get_object_or_404, redirect, render
    from django.urls import reverse

    from .models import Timetable
    from .views import _nav

    timetable = get_object_or_404(Timetable.objects.select_related("school"), pk=pk)
    active = active_job(timetable)
    if request.GET.get("durum") == "1":
        job = active or timetable.improve_jobs.first()
        return JsonResponse({"job": _state(job)})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "start":
            minutes = int(request.POST.get("dakika") or 20)
            if minutes not in LIMITS:
                minutes = 20
            if active is None:
                start(timetable, request.user, minutes)
                messages.success(request, f"İyileştirme başladı ({minutes} dk). Bu sayfadan ayrılabilirsiniz; sonuç öneri olarak burada bekler.")
        elif action == "stop" and active is not None:
            request_stop(active)
            messages.info(request, "Durduruluyor: o ana kadar bulunan iyileştirme öneri olarak kaydedilecek.")
        elif action in ("review", "discard"):
            job = get_object_or_404(J, pk=request.POST.get("is"), timetable=timetable)
            if action == "discard":
                job.delete()
                messages.info(request, "Sonuç silindi.")
            elif job.result:
                request.session[f"resolve-{timetable.pk}"] = {"label": LABEL, "proposals": [job.result], "availability": None}
                return redirect(reverse("timetable:solution_center", args=[timetable.pk]) + "?goster=1")
        return redirect("timetable:school_improve", pk=timetable.pk)
    latest = timetable.improve_jobs.exclude(status__in=[J.QUEUED, J.RUNNING]).first()
    return render(request, "timetable/school_improve.html", _nav(
        timetable.school, "solution", timetable=timetable, active=active, latest=latest, limits=LIMITS,
        worker=jobs.worker_mode()))
