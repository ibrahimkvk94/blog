"""Programı yerel ağa açar (Windows'ta da çalışan waitress sunucusu; kapalı ağ paketi bunu kullanır).

    python manage.py sunucu            # SUNUCU_PORT (varsayılan 8000), tüm ağ arayüzleri
    python manage.py sunucu --port 8080
"""

import os
import socket
import threading

from django.conf import settings
from django.core.management.base import BaseCommand


def lan_addresses():
    """Bu bilgisayarın ağdaki IPv4 adresleri (diğer bilgisayarlar bunlarla bağlanır)."""
    found = set()
    try:
        found.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:  # varsayılan ağ arayüzü (paket gönderilmez; yalnızca yönlendirme seçilir)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


def tailscale_names():
    """Tailscale açıksa bu bilgisayarın Tailscale adresleri ve MagicDNS adı (yoksa boş liste)."""
    import ipaddress
    import json
    import shutil
    import subprocess

    exe = shutil.which("tailscale") or next(
        (p for p in (r"C:\Program Files\Tailscale\tailscale.exe",) if os.path.isfile(p)), None)
    names = []
    if exe:
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5).stdout
            me = json.loads(out or "{}").get("Self") or {}
            dns = (me.get("DNSName") or "").rstrip(".")
            names += [dns] if dns else []
            names += [ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip]
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    tailnet = ipaddress.ip_network("100.64.0.0/10")  # Tailscale adres aralığı
    names += [a for a in lan_addresses() if ipaddress.ip_address(a) in tailnet and a not in names]
    return names


def backup_loop(hours, stop):
    """Sunucu açık kaldıkça son yedek `hours` saatten eskiyse yedek alır (saatte bir denetler)."""
    from django.db import connection

    from timetable import backup

    stop.wait(60)  # açılışta sunucuyu bekletmesin
    while not stop.is_set():
        try:
            path = backup.ensure_recent(hours)
            if path:
                print(f"Otomatik yedek alındı: {path}", flush=True)
        except Exception as exc:  # yedek alınamasa da sunucu çalışmaya devam etsin
            print(f"Otomatik yedek alınamadı: {exc}", flush=True)
        finally:
            connection.close()
        stop.wait(3600)


class Command(BaseCommand):
    help = "Ders programını yerel ağdaki tüm bilgisayarlara açar (waitress)."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=int(os.environ.get("SUNUCU_PORT", "8000")))
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--threads", type=int, default=8)
        parser.add_argument("--yedek-saat", type=int, default=int(os.environ.get("AUTO_BACKUP_HOURS", "24")),
                            help="Kaç saatte bir otomatik yedek (0 = kapalı)")

    def handle(self, *args, **options):
        from waitress import serve

        from config.wsgi import application

        port = options["port"]
        tailscale = tailscale_names()
        self.stdout.write(self.style.SUCCESS("Ders Programı çalışıyor. Ağdaki bilgisayarlar tarayıcıya şu adresi yazsın:"))
        for address in [a for a in lan_addresses() if a not in tailscale] or ["<bu bilgisayarın IP adresi>"]:
            self.stdout.write(f"    http://{address}:{port}/")
        if tailscale:
            self.stdout.write(self.style.SUCCESS("Tailscale ile (ağınıza eklediğiniz ya da paylaştığınız kişiler, her yerden):"))
            for address in tailscale:
                self.stdout.write(f"    http://{address}:{port}/")
        self.stdout.write(f"Bu bilgisayardan: http://127.0.0.1:{port}/")
        if settings.DEBUG:
            self.stdout.write(self.style.WARNING("Uyarı: DJANGO_DEBUG=1 açık; ağ kurulumunda .env dosyasında DJANGO_DEBUG=0 olmalı."))
        if options["yedek_saat"] > 0:
            threading.Thread(target=backup_loop, args=(options["yedek_saat"], threading.Event()), daemon=True).start()
            self.stdout.write(f"Otomatik yedek: {options['yedek_saat']} saatte bir (yedekler klasörü).")
        self.stdout.write("Kapatmak için bu pencerede Ctrl+C'ye basın ya da pencereyi kapatın.")
        serve(application, host=options["host"], port=port, threads=options["threads"], ident="DersProgrami")
