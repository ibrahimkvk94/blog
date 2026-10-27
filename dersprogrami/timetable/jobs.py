"""Uzun süren üretim işlerini arka planda çalıştırır.

Ek altyapı (Redis/Celery) gerektirmemek için işler aynı süreçte ayrı bir iş parçacığında çalışır.
İlerleme ve durdurma bilgisi bellekte tutulur: CP-SAT çözüm bildirimini kendi iş parçacığından
yaptığı için oradan veritabanına yazılmaz. Bu yüzden ilerleme ve durdurma, işi çalıştıran süreç
içinde geçerlidir; çok süreçli dağıtımda ya da Celery'ye geçişte yeniden ele alınmalıdır.
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


def start(timetable_id, func, *args):
    """func(timetable_id, *args) çağrısını arka planda (ya da ayara göre hemen) çalıştırır."""
    handle_for(timetable_id)
    if not getattr(settings, "TIMETABLE_RUN_IN_BACKGROUND", True):
        try:
            func(timetable_id, *args)
        finally:
            _forget(timetable_id)
        return
    thread = threading.Thread(target=_run, args=(timetable_id, func, args), daemon=True, name=f"timetable-{timetable_id}")
    thread.start()
