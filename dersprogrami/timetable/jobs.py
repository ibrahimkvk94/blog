"""Uzun süren üretim işlerini arka planda çalıştırır.

İki çalışma biçimi vardır (TIMETABLE_JOB_BACKEND):
- "thread" (yerel kurulum): iş web sürecinde ayrı bir iş parçacığında çalışır. İlerleme ve durdurma
  bellektedir (CP-SAT çözüm bildirimini kendi iş parçacığından yaptığı için oradan veritabanına
  yazılmaz).
- "worker" (sunucu): iş veritabanında sıraya girer (Timetable.job_state="queued"), ayrı
  `python manage.py calisan` süreci alır ve çalıştırır. Çalışan, ilerlemeyi ve nabzı ayrı bir
  izleyici iş parçacığından veritabanına yazar ve durdurma isteğini oradan okur. Böylece web
  yeniden başlasa da üretim sürer ve aynı anda başlatılan üretimler sıraya girer.
"""

import threading

from django.conf import settings
from django.db import close_old_connections, connection

from .solver.cpsat import StopHandle

_handles = {}
_progress = {}
_lock = threading.Lock()


def handle_for(timetable_id):
    with _lock:
        return _handles.setdefault(timetable_id, StopHandle())


def is_alive(timetable_id):
    with _lock:
        return timetable_id in _handles


def stop(timetable_id):
    with _lock:
        handle = _handles.get(timetable_id)
    if handle is not None:
        handle.stop()


def set_progress(timetable_id, progress):
    """Çözücü iş parçacığından çağrılır; veritabanına dokunmaz."""
    with _lock:
        _progress[timetable_id] = dict(progress)


def progress(timetable_id):
    with _lock:
        return dict(_progress.get(timetable_id, {}))


def _forget(timetable_id):
    with _lock:
        _handles.pop(timetable_id, None)
        _progress.pop(timetable_id, None)


def _run(timetable_id, func, args):
    close_old_connections()
    try:
        func(timetable_id, *args)
    finally:
        _forget(timetable_id)
        connection.close()


def worker_mode():
    return getattr(settings, "TIMETABLE_JOB_BACKEND", "thread") == "worker"


def start(timetable_id, func, *args):
    """func(timetable_id, *args) çağrısını arka planda (ya da ayara göre hemen) çalıştırır."""
    if worker_mode():
        from .models import Timetable

        report = dict(Timetable.objects.get(pk=timetable_id).report)
        report["job"] = {"func": f"{func.__module__}.{func.__name__}", "args": list(args)}
        Timetable.objects.filter(pk=timetable_id).update(job_state="queued", report=report)
        return
    handle_for(timetable_id)
    if not getattr(settings, "TIMETABLE_RUN_IN_BACKGROUND", True):
        try:
            func(timetable_id, *args)
        finally:
            _forget(timetable_id)
        return
    thread = threading.Thread(target=_run, args=(timetable_id, func, args), daemon=True, name=f"timetable-{timetable_id}")
    thread.start()


# --- çalışan süreç (worker) ----------------------------------------------------------------------

HEARTBEAT_SECONDS = 2
STALE_AFTER_SECONDS = 180


def claim_next():
    """Sıradaki işi atomik olarak alır; yoksa None."""
    from django.utils import timezone

    from .models import Timetable

    for timetable in Timetable.objects.filter(job_state="queued").order_by("started_at", "pk")[:5]:
        if Timetable.objects.filter(pk=timetable.pk, job_state="queued").update(job_state="running", heartbeat=timezone.now()):
            return Timetable.objects.get(pk=timetable.pk)
    return None


def run_claimed(timetable):
    """Çalışan süreçte bir işi çalıştırır; izleyici iş parçacığı ilerleme/nabız yazar, durdurmayı okur."""
    import importlib

    from django.utils import timezone

    from .models import Timetable

    job = timetable.report.get("job") or {}
    module_name, _, func_name = job.get("func", "timetable.services.run_generation").rpartition(".")
    func = getattr(importlib.import_module(module_name), func_name)
    handle = handle_for(timetable.pk)
    done = threading.Event()

    def watch():
        close_old_connections()
        try:
            while not done.wait(HEARTBEAT_SECONDS):
                row = Timetable.objects.filter(pk=timetable.pk).values("cancel_requested", "report", "status").first()
                if row is None or row["status"] != Timetable.RUNNING:
                    continue
                if row["cancel_requested"]:
                    handle.stop()
                report = dict(row["report"])
                report["progress"] = progress(timetable.pk)
                Timetable.objects.filter(pk=timetable.pk, status=Timetable.RUNNING).update(heartbeat=timezone.now(), report=report)
        finally:
            connection.close()

    watcher = threading.Thread(target=watch, daemon=True, name=f"watch-{timetable.pk}")
    watcher.start()
    try:
        func(timetable.pk, *job.get("args", []))
    finally:
        done.set()
        watcher.join(timeout=HEARTBEAT_SECONDS * 2)
        _forget(timetable.pk)
        Timetable.objects.filter(pk=timetable.pk).update(job_state="")


def queued_or_alive(timetable):
    """Çalışan kipte: iş sırada mı ya da nabzı taze mi?"""
    from django.utils import timezone

    if timetable.job_state == "queued":
        return True
    if timetable.job_state == "running" and timetable.heartbeat:
        return (timezone.now() - timetable.heartbeat).total_seconds() < STALE_AFTER_SECONDS
    return False
