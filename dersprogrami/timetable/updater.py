"""Sistem güncelleme (Merkez → Sistem güncelleme): yeni sürümü denetler, indirir ve sunucuyu yeniden başlatır.

İndirme (git) bu sayfadan yapılır; yeniden başlatmayı ve ardından paket / veritabanı güncellemesini başlatıcı
(baslat.py) yapar: sunucu 3 koduyla çıkar, başlatıcı hazırlığı yapıp sunucuyu yeniden açar. Başlatıcı olmadan
çalışan kurulumlarda (eski bat dosyası, kapalı ağ paketi, Docker) sayfa yalnızca ne yapılacağını söyler.
"""

import json
import os
import subprocess
import threading
import time

from django.conf import settings

RESTART = 3  # baslat.py ile aynı
STATUS = settings.BASE_DIR / "guncelleme-durum.json"
REQUEST = settings.BASE_DIR / "guncelleme-istek.json"


def _git(*args, timeout=60):
    """(başarılı mı, çıktı). git yoksa ya da zaman aşımında (False, açıklama)."""
    try:
        done = subprocess.run(["git", *args], cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False, "git kurulu değil"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return done.returncode == 0, ((done.stdout or "") + (done.stderr or "")).strip()


def supervised():
    """Sunucu başlatıcıyla mı çalışıyor (yeniden başlatılabilir mi)? Değer: "yerel" / "paylas" / ""."""
    return os.environ.get("DERSPROGRAMI_BASLATICI", "")


def is_git():
    return _git("rev-parse", "--is-inside-work-tree", timeout=10)[0]


def _commits(spec, limit=60):
    ok, out = _git("log", spec, f"-{limit}", "--format=%h%x1f%cI%x1f%s", timeout=20)
    rows = []
    for line in out.splitlines() if ok else []:
        parts = line.split("\x1f")
        if len(parts) == 3:
            rows.append({"hash": parts[0], "date": parts[1][:16].replace("T", " "), "subject": parts[2]})
    return rows


def current():
    rows = _commits("HEAD", 1)
    return rows[0] if rows else None


def local_changes():
    """Projede elle değiştirilmiş (git'in izlediği) dosyalar: güncelleme bunları ezmez, durur."""
    ok, out = _git("status", "--porcelain", "--untracked-files=no", timeout=20)
    return [line[3:] for line in out.splitlines()] if ok else []


def check():
    """Sunucudaki yeni sürümler: {"ok", "error", "incoming": [...], "rewritten": bool}."""
    ok, out = _git("fetch", "--quiet", timeout=90)
    if not ok:
        return {"ok": False, "error": "Güncelleme sunucusuna ulaşılamadı (internet bağlantısını kontrol edin). " + out[-300:]}
    ok, counts = _git("rev-list", "--left-right", "--count", "HEAD...@{u}", timeout=20)
    if not ok:
        return {"ok": False, "error": "Bu kurulumun izlediği bir güncelleme dalı yok. " + counts[-300:]}
    ahead, behind = (int(n) for n in counts.split())
    return {"ok": True, "incoming": _commits("HEAD..@{u}"), "behind": behind, "rewritten": ahead > 0 and behind > 0}


def pull():
    """Yeni sürümü indirir (calistir.bat ile aynı kurallar). (başarılı mı, ileti)."""
    ok, out = _git("-c", "advice.diverging=false", "pull", "--ff-only", timeout=180)
    if ok:
        return True, "Yeni sürüm indirildi."
    if local_changes():
        return False, "Projede elle değiştirilmiş dosyalar var; güncelleme bunları ezmemek için durdu."
    _git("branch", "-f", "onceki-surum", "HEAD")
    ok, out2 = _git("reset", "--hard", "@{u}", timeout=60)
    if ok:
        return True, 'Sunucudaki sürüm yeniden düzenlenmişti; en son sürüme geçildi (eski hal "onceki-surum" dalında).'
    return False, "İndirilemedi: " + (out2 or out)[-400:]


def request_restart(before):
    """Yanıt gönderildikten sonra sunucuyu kapatır; başlatıcı hazırlığı yapıp yeniden açar."""
    try:
        REQUEST.write_text(json.dumps({"from": before}), encoding="utf-8")
    except OSError:
        pass

    def stop():
        time.sleep(1.5)
        os._exit(RESTART)

    threading.Thread(target=stop, daemon=True).start()


def last_result():
    """Son güncellemenin sonucu (başlatıcının yazdığı): {"at", "from", "to", "steps": [...]}."""
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("from") and data.get("to") and data["from"] != data["to"]:
        data["changes"] = _commits(f"{data['from']}..{data['to']}")
    return data
