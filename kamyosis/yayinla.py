"""KAMYOSİS'i kurum içi ağda yayınlar (waitress).

    .venv\\Scripts\\python.exe yayinla.py            # 0.0.0.0:8000
    .venv\\Scripts\\python.exe yayinla.py --port 8080
"""

import argparse
import os
import socket
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("KAMYOSIS_DEBUG", "0")
# Ders programı üretimleri ayrı "çalışan" süreçte; çözücü bütün çekirdekleri almasın ki site yavaşlamasın
os.environ.setdefault("TIMETABLE_JOB_BACKEND", "worker")
os.environ.setdefault("SOLVER_WORKERS", str(max(1, (os.cpu_count() or 4) - 2)))

KOK = os.path.dirname(os.path.abspath(__file__))


def _yerel_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _penceresiz_ise_kayda_yonlendir():
    """pythonw.exe ile (penceresiz) çalışırken çıktıları kayitlar/sunucu.log dosyasına yazar."""
    if sys.stdout is not None:
        return
    import logging
    from pathlib import Path

    klasor = Path(__file__).resolve().parent / "kayitlar"
    klasor.mkdir(exist_ok=True)
    dosya = open(klasor / "sunucu.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = dosya
    logging.basicConfig(stream=dosya, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _eski_calisanlari_durdur():
    """Önceki çalıştırmadan kalmış (sunucu zorla kapatılmışsa) çalışan süreçleri kapatır."""
    import subprocess

    komut = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*manage.py*calisan*' -and "
             "$_.CommandLine -like '*" + KOK.replace("'", "''") + "*' } | "
             "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", komut], capture_output=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _calisani_baslat():
    """Ders programı üretim kuyruğunu işleyen `manage.py calisan` sürecini başlatır; sunucu kapanınca o da kapanır."""
    import atexit
    import subprocess

    if os.name == "nt":
        _eski_calisanlari_durdur()
    kayit = open(os.path.join(KOK, "kayitlar", "calisan.log"), "a", encoding="utf-8", buffering=1)
    surec = subprocess.Popen(
        [sys.executable, os.path.join(KOK, "manage.py"), "calisan"], cwd=KOK, stdout=kayit, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    atexit.register(surec.terminate)
    return surec


def main():
    _penceresiz_ise_kayda_yonlendir()
    os.makedirs(os.path.join(KOK, "kayitlar"), exist_ok=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)
    call_command("ders_programi_yetki_esitle", verbosity=0)
    call_command("ders_programi_kunye_esitle", verbosity=0)
    if os.environ["TIMETABLE_JOB_BACKEND"] == "worker":
        _calisani_baslat()

    from waitress import serve

    from config.wsgi import application

    from datetime import datetime

    print(f"[{datetime.now():%d.%m.%Y %H:%M:%S}] KAMYOSİS yayında:  http://{_yerel_ip()}:{args.port}   (bu bilgisayardan: http://127.0.0.1:{args.port})")
    print("Durdurmak için Ctrl+C")
    serve(application, host=args.host, port=args.port, threads=8)


if __name__ == "__main__":
    sys.exit(main())
