"""Yedekleme: tüm veriyi (kurumlar, programlar, kullanıcılar) sıkıştırılmış JSON olarak kaydeder.

SQLite ve PostgreSQL'de aynı biçim kullanılır; geri yükleme:
    python manage.py loaddata yedekler/yedek-2026-10-28-0300.json.gz
"""

import gzip
import re
from datetime import datetime
from io import StringIO

from django.conf import settings
from django.core.management import call_command

NAME = re.compile(r"^yedek-\d{4}-\d{2}-\d{2}-\d{4,6}\.json\.gz$")
EXCLUDE = ["contenttypes", "auth.permission", "admin.logentry", "sessions"]


def directory():
    path = settings.BACKUP_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def create():
    buffer = StringIO()
    call_command("dumpdata", natural_foreign=True, natural_primary=True, exclude=EXCLUDE, stdout=buffer)
    name = f"yedek-{datetime.now():%Y-%m-%d-%H%M%S}.json.gz"
    path = directory() / name
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
