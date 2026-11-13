"""Ana görünümdeki "İhlalleri çöz" ve "Cezayı düşür" düğmelerinin arka plan işi.

Çözücü önceden web isteğinin içinde çalışıyordu: istek bitene kadar (40 sn – 2 dk) sunucu o çekirdekleri
kullanıyor, vekil sunucu zaman aşımına düşebiliyordu. Şimdi iş, okul geneli iyileştirmeyle aynı kuyruktan
(ImproveJob, tür "resolve" / "penalty") yürür: yerel kurulumda web sürecinde ayrı iş parçacığı, sunucu
kurulumunda `calisan` süreci (school_improve.claim_next). Sayfa ilerlemeyi okur; "Durdur" o ana kadar bulunan
en iyi sonucu uygular.

Sonuç doğrudan programa yazılır ve "Geri al" ile geri alınabilir. İş sürerken program elle değiştirildiyse sonuç
uygulanmaz (yoksa kullanıcının değişikliği ezilirdi).
"""

import logging
import threading
import time

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import jobs, school_improve, services
from .models import ImproveJob, Timetable
from .solver.cpsat import StopHandle

J = ImproveJob
log = logging.getLogger(__name__)

# Süre seçenekleri (saniye). "İhlalleri çöz": 40 ve 90 sn yalnızca az değişiklikle onarır; services.DEEP_RESOLVE ve
# üstü takılınca gün komşuluğuna geçer. "Cezayı düşür": uzun seçenekler ceza STALL saniye düşmezse erken biter.
RESOLVE_LIMITS = (40, 90, 600, 1800)
PENALTY_LIMITS = (60, 300, 900)
STALL = 180
BEAT = 2.0  # ilerleme / nabız / durdurma isteği aralığı (sn)


class JobError(Exception):
    pass


def start(timetable, user, kind, seconds):
    """İşi başlatır; programda başka bir iyileştirme işi sürüyorsa onu döndürür (türü farklı olabilir)."""
    limits = RESOLVE_LIMITS if kind == J.RESOLVE else PENALTY_LIMITS
    seconds = seconds if seconds in limits else limits[0]
    return school_improve.start(timetable, user, 0, kind=kind, seconds=seconds)


def latest(timetable):
    """Programın en son "İhlalleri çöz" / "Cezayı düşür" işi (sürüyorsa o)."""
    job = timetable.improve_jobs.filter(kind__in=[J.RESOLVE, J.PENALTY]).order_by("-created_at").first()
    if job is not None and job.active:
        school_improve.refresh_stale(job)
        job.refresh_from_db()
    return job


def state(job):
    if job is None:
        return None
    return {"id": job.pk, "kind": job.kind, "kind_label": job.get_kind_display(), "status": job.status,
            "active": job.active, "progress": job.progress, "result": job.result, "error": job.error,
            "stop_requested": job.stop_requested, "time_limit": job.time_limit}


def _cells(timetable):
    return {c["id"]: (c["day"], c["period"], c["classroom_id"], list(c["extra_rooms"] or []))
            for c in timetable.cards.values("id", "day", "period", "classroom_id", "extra_rooms")}


def _watch(job_id, progress, handle, done, began):
    """Ayrı iş parçacığı (kendi veritabanı bağlantısı): ilerlemeyi ve nabzı yazar, durdurma isteğini okur.
    Çözücü uzun turlarda bekletirken de sayfa ilerlemeyi görür ve "Durdur" çözücüyü hemen keser."""
    try:
        while not done.wait(BEAT):
            J.objects.filter(pk=job_id).update(progress={**progress, "elapsed": int(time.monotonic() - began)},
                                               heartbeat=timezone.now())
            if J.objects.filter(pk=job_id, stop_requested=True).exists():
                handle.stop()
    finally:
        connection.close()


def run(job):
    """school_improve.run tarafından çağrılır (iş "sırada" ya da çalışanın aldığı "çalışıyor" durumunda)."""
    now = timezone.now()
    J.objects.filter(pk=job.pk).update(status=J.RUNNING, started_at=now, heartbeat=now)
    began = time.monotonic()
    unit = "ihlal" if job.kind == J.RESOLVE else "ceza"
    progress = {"phase": "Program yükleniyor", "unit": unit, "limit": job.time_limit, "elapsed": 0}
    handle, done = StopHandle(), threading.Event()
    # Arka planda (iş parçacığı ya da çalışan süreç) izleyici çalışır; anında çalıştırmada (testler) gerekmez.
    if jobs.worker_mode() or getattr(settings, "TIMETABLE_RUN_IN_BACKGROUND", True):
        threading.Thread(target=_watch, args=(job.pk, progress, handle, done, began), daemon=True,
                         name=f"quick-watch-{job.pk}").start()
    try:
        timetable = Timetable.objects.select_related("school").get(pk=job.timetable_id)
        snapshot = _cells(timetable)
        if job.kind == J.RESOLVE:
            def on_progress(p):
                progress["phase"] = ("Gün komşuluğu: 2–3 günün dersleri birlikte yeniden diziliyor"
                                     if p.get("stage") == "days" else "Az değişiklikle onarılıyor")
                progress.setdefault("before", p.get("violations"))
                progress["now"] = p.get("violations")
                progress["round"] = p.get("round")

            found = services.resolve_search(timetable, job.time_limit, stop_handle=handle, on_progress=on_progress)
            note = "ihlaller çözüldü"
        else:
            def on_progress(p):
                progress["phase"] = "Ceza 2–3 günlük gruplar halinde yeniden dizilerek düşürülüyor"
                progress.setdefault("before", p.get("objective"))
                progress["now"] = p.get("objective")
                progress["round"] = p.get("round")

            stall = STALL if job.time_limit >= 300 else None
            found = services.penalty_search(timetable, job.time_limit, stall=stall, stop_handle=handle,
                                            on_progress=on_progress)
            note = "ceza düşürüldü"
        result = {"ok": found["ok"], "before": found["before"], "after": found["after"], "moved": 0,
                  "stopped": handle.stopped}
        if found["result"] is None:
            result["message"] = (f"Durduruldu; o ana kadar {'ihlal azalmadı' if job.kind == J.RESOLVE else 'ceza düşmedi'}."
                                 if handle.stopped and found["ok"] and found["before"] else found["message"])
        else:
            if _cells(timetable) != snapshot:
                raise JobError("Program bu sırada elle değiştirildi; ezilmemesi için sonuç uygulanmadı. Yeniden başlatın.")
            changed, shifted = services.write_placements(timetable, found["problem"], found["result"], note)
            result.update(moved=changed, shifted=shifted)
            if job.kind == J.RESOLVE:
                result["message"] = services.resolve_message(found["before"], found["after"], changed, shifted)
            else:
                Timetable.objects.filter(pk=timetable.pk).update(objective=found["after"])
                result["message"] = services.penalty_message(found["before"], found["after"], shifted)
        progress.update(phase="Bitti", now=found["after"], elapsed=int(time.monotonic() - began))
        J.objects.filter(pk=job.pk).update(status=J.DONE, result=result, progress=dict(progress),
                                           finished_at=timezone.now(), heartbeat=timezone.now())
    except Exception as exc:  # iş "çalışıyor" durumunda asılı kalmasın
        if not isinstance(exc, JobError):
            log.exception("%s işi #%s başarısız", job.kind, job.pk)
        J.objects.filter(pk=job.pk).update(status=J.FAILED, error=str(exc)[:2000], finished_at=timezone.now())
    finally:
        done.set()
