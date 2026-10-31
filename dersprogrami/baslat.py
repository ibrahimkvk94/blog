"""Ders Programı başlatıcısı: güncelle → hazırla → sunucuyu çalıştır.

calistir.bat / paylas.bat (ve .sh) bunu çağırır. Sunucu 3 koduyla çıkarsa (Merkez → Sistem güncelleme sayfasında
"Güncelle ve yeniden başlat") baştan alınır: paketler ve veritabanı güncellenir, sunucu yeniden açılır. Böylece
güncelleme için pencereyi kapatıp açmak gerekmez.

    python baslat.py yerel     # yalnızca bu bilgisayar (http://127.0.0.1:8000/)
    python baslat.py paylas    # ağ / Tailscale ile başkaları da bağlanır
"""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESTART = 3  # sunucunun "güncellendim, yeniden başlat" çıkış kodu
STATUS = ROOT / "guncelleme-durum.json"
REQUEST = ROOT / "guncelleme-istek.json"  # sayfa yazar: güncellemeden önceki sürüm
PORT = 8000


def say(text):
    print(text, flush=True)


def run(args, quiet=True, timeout=None):
    """Komutu proje klasöründe çalıştırır: (başarılı mı, çıktının son satırları)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        done = subprocess.run(args, cwd=ROOT, capture_output=quiet, text=True, timeout=timeout, env=env,
                              encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    tail = "\n".join(((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-8:]) if quiet else ""
    return done.returncode == 0, tail


def git(*args, timeout=120):
    return run(["git", *args], timeout=timeout)


def head():
    ok, out = git("rev-parse", "--short", "HEAD", timeout=10)
    return out.strip() if ok else ""


def git_update():
    """calistir.bat'taki güncellemenin aynısı: hızlı ileri sar; sunucudaki geçmiş yeniden yazıldıysa ve yerel
    değişiklik yoksa en son sürüme geç (eski hal "onceki-surum" dalında)."""
    if not git("rev-parse", "--is-inside-work-tree", timeout=10)[0]:
        say("Otomatik güncelleme kapalı: proje git ile indirilmemiş. Bilgi için KURULUM.md dosyasına bakın.")
        return
    ok, out = git("-c", "advice.diverging=false", "pull", "--ff-only")
    if ok:
        say(out.splitlines()[-1] if out else "Güncel.")
        return
    if not git("fetch")[0]:
        say("Güncelleme alınamadı: internete bağlanılamadı. Mevcut sürümle devam ediliyor.")
        return
    if not git("diff", "--quiet", "HEAD", "--")[0]:
        say("Güncelleme atlandı: yerel değişiklik var. Mevcut sürümle devam ediliyor.")
        return
    git("branch", "-f", "onceki-surum", "HEAD")
    if git("reset", "--hard", "@{u}")[0]:
        say('Sunucudaki sürüm yeniden düzenlenmişti; en son sürüme geçildi. Eski hal "onceki-surum" dalında.')


def ensure_secret_key():
    """Ağa açık kullanımda bu bilgisayara özel gizli anahtar (.env'de yoksa bir kez üretilir)."""
    env = ROOT / ".env"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if "DJANGO_SECRET_KEY=" not in text:
        sep = "" if not text or text.endswith("\n") else "\n"
        env.write_text(text + sep + "DJANGO_SECRET_KEY=" + secrets.token_urlsafe(50) + "\n", encoding="utf-8")


def prepare(mode, env, before):
    """Paketler, veritabanı ve (ağ modunda) statik dosyalar. Sonuç Sistem güncelleme sayfası için yazılır."""
    python = sys.executable
    steps = []
    for title, args in [
        ("Paketler", [python, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r", "requirements.txt"]),
        ("Veritabanı", [python, "manage.py", "migrate", "--noinput"]),
        *([("Statik dosyalar", [python, "manage.py", "collectstatic", "--noinput"])] if mode == "paylas" else []),
    ]:
        say(f"    {title}...")
        done = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = "\n".join(((done.stdout or "") + (done.stderr or "")).strip().splitlines()[-12:])
        steps.append({"title": title, "ok": done.returncode == 0, "output": output if done.returncode else ""})
        if done.returncode:
            say(f"    {title} adımı başarısız:\n{output}")
    try:
        STATUS.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "from": before, "to": head(), "steps": steps},
                                     ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return all(s["ok"] for s in steps)


def serve(mode, env):
    """Sunucuyu çalıştırır, çıkış kodunu döndürür. Ctrl+C başlatıcıyı da kapatır."""
    python = sys.executable
    if mode == "paylas":
        args = [python, "manage.py", "sunucu", "--port", str(PORT)]
    else:
        # Kod değişince kendiliğinden yeniden yüklenme kapalı: güncellemede yeniden başlatmayı başlatıcı yapar
        # (önce veritabanını günceller).
        args = [python, "manage.py", "runserver", f"127.0.0.1:{PORT}", "--noreload"]
    child = subprocess.Popen(args, cwd=ROOT, env=env)
    try:
        return child.wait()
    except KeyboardInterrupt:
        try:
            child.wait(timeout=10)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            child.kill()
        raise


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "yerel"
    if mode not in ("yerel", "paylas"):
        say("Kullanım: python baslat.py yerel|paylas")
        return 2
    env = {**os.environ, "DERSPROGRAMI_BASLATICI": mode}
    if mode == "paylas":
        ensure_secret_key()
        # Yalnızca bu sunucu için: hata ayıklama kapalı, Tailscale adı / IP'siyle gelen isteklere izin.
        env.update({"DJANGO_DEBUG": "0", "DJANGO_ALLOWED_HOSTS": "*"})
    first = True
    while True:
        before = head()
        if not first:
            try:
                before = json.loads(REQUEST.read_text(encoding="utf-8")).get("from", before)
                REQUEST.unlink()
            except (OSError, ValueError):
                pass
        if first:
            say("[1/3] Güncellemeler kontrol ediliyor...")
            git_update()
        say("[2/3] Paketler ve veritabanı güncelleniyor...")
        prepare(mode, env, "" if first else before)
        if first:
            subprocess.run([sys.executable, "manage.py", "yedekle"], cwd=ROOT, env=env, capture_output=True)
            threading.Timer(4, webbrowser.open, args=(f"http://127.0.0.1:{PORT}/",)).start()
        say(f"[3/3] Ders Programı çalışıyor: http://127.0.0.1:{PORT}/  (kapatmak için Ctrl+C ya da pencereyi kapatın)")
        try:
            code = serve(mode, env)
        except KeyboardInterrupt:
            say("Kapatıldı.")
            return 0
        if code != RESTART:
            say(f"Sunucu durdu (kod {code}).")
            return code
        say("\n=== Güncelleme yüklendi; yeniden başlatılıyor ===")
        first = False


if __name__ == "__main__":
    sys.exit(main())
