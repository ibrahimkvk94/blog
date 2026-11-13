"""Toplu silme / sıfırlama öncesi veritabanının tutarlı yedeği (yedekler/sifirlama/; en yeni 20 tanesi kalır)."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection

SAKLA = 20


def sifirlama_yedegi(etiket):
    """Yedeğin yolunu döner; testlerde (bellek içi veritabanı) ya da SIFIRLAMA_YEDEGI=False iken yedek almaz."""
    if not getattr(settings, "SIFIRLAMA_YEDEGI", True) or "memory" in str(connection.settings_dict.get("NAME", "")):
        return None
    klasor = Path(settings.BASE_DIR) / "yedekler" / "sifirlama"
    klasor.mkdir(parents=True, exist_ok=True)
    etiket = re.sub(r"[^a-z0-9_-]+", "-", etiket.lower()).strip("-")[:40] or "sifirlama"
    hedef = klasor / f"db_{datetime.now():%Y%m%d_%H%M%S}_{etiket}.sqlite3"
    connection.ensure_connection()
    with sqlite3.connect(hedef) as yedek:
        connection.connection.backup(yedek)
    yedek.close()
    for eski in sorted(klasor.glob("db_*.sqlite3"))[:-SAKLA]:
        eski.unlink()
    return hedef
