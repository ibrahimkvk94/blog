"""Yedekleme: tüm veriyi (kurumlar, programlar, kullanıcılar) sıkıştırılmış JSON olarak kaydeder.

SQLite ve PostgreSQL'de aynı biçim kullanılır. Geri yükleme Merkez paneli → Yedekler ekranından (restore)
ya da boş bir kurulumda:
    python manage.py loaddata yedekler/yedek-2026-10-28-0300.json.gz
"""

import gzip
import json
import re
import time
from datetime import datetime
from io import StringIO

from django.conf import settings
from django.core.management import call_command
from django.db import transaction

NAME = re.compile(r"^yedek-\d{4}-\d{2}-\d{2}-\d{4,6}\.json\.gz$")
EXCLUDE = ["contenttypes", "auth.permission", "admin.logentry", "sessions"]


def directory():
    path = settings.BACKUP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _new_path():
    """Saniyeli yeni yedek adı; aynı saniyede alınmış yedeğin üzerine yazılmaz (bir sonraki saniye beklenir)."""
    while True:
        path = directory() / f"yedek-{datetime.now():%Y-%m-%d-%H%M%S}.json.gz"
        if not path.exists():
            return path
        time.sleep(0.2)


def create():
    buffer = StringIO()
    call_command("dumpdata", natural_foreign=True, natural_primary=True, exclude=EXCLUDE, stdout=buffer)
    path = _new_path()
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(buffer.getvalue())
    prune()
    return path


def listing():
    files = sorted((p for p in directory().iterdir() if NAME.match(p.name)), reverse=True)
    return [{"name": p.name, "size": p.stat().st_size, "created": datetime.fromtimestamp(p.stat().st_mtime)} for p in files]


def prune():
    for item in listing()[settings.BACKUP_KEEP:]:
        (directory() / item["name"]).unlink(missing_ok=True)


def path_of(name):
    if not NAME.match(name or ""):
        return None
    path = directory() / name
    return path if path.exists() else None


def latest_age_hours():
    """En son yedeğin yaşı (saat); hiç yedek yoksa None."""
    items = listing()
    if not items:
        return None
    return (datetime.now() - items[0]["created"]).total_seconds() / 3600


def ensure_recent(hours):
    """Son yedek `hours` saatten eskiyse yeni yedek alır (sunucu çalışırken otomatik yedek)."""
    age = latest_age_hours()
    if age is None or age >= hours:
        return create()
    return None


def save_upload(uploaded):
    """Başka bilgisayardan gelen yedek dosyasını yedek klasörüne alır; geçerli yedek değilse ValueError."""
    raw = uploaded.read()
    try:
        data = json.loads(gzip.decompress(raw).decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        raise ValueError("Dosya bir Ders Programı yedeği değil (.json.gz bekleniyor).")
    if not isinstance(data, list) or not any(isinstance(o, dict) and o.get("model", "").startswith("timetable.") for o in data[:2000]):
        raise ValueError("Dosyada ders programı verisi yok.")
    path = _new_path()
    path.write_bytes(raw)
    return path


def restore(path):
    """Veritabanını yedekteki haline döndürür. Önce mevcut durumun yedeği alınır; yükleme başarısız
    olursa hiçbir şey değişmez (tek işlem). Oturumlar silinir: herkes yeniden giriş yapar.
    Dönüş: alınan güvenlik yedeğinin yolu."""
    safety = create()
    with transaction.atomic():
        call_command("flush", interactive=False, verbosity=0)
        call_command("loaddata", str(path), verbosity=0)
    from .problem_cache import invalidate

    invalidate()
    return safety
