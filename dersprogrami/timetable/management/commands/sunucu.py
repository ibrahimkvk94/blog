"""Programı yerel ağa açar (Windows'ta da çalışan waitress sunucusu; kapalı ağ paketi bunu kullanır).

    python manage.py sunucu            # SUNUCU_PORT (varsayılan 8000), tüm ağ arayüzleri
    python manage.py sunucu --port 8080
"""

import os
import socket

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


class Command(BaseCommand):
    help = "Ders programını yerel ağdaki tüm bilgisayarlara açar (waitress)."

    def add_arguments(self, parser):
        parser.add_argument("--port", type=int, default=int(os.environ.get("SUNUCU_PORT", "8000")))
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--threads", type=int, default=8)

    def handle(self, *args, **options):
        from waitress import serve

        from config.wsgi import application

        port = options["port"]
        self.stdout.write(self.style.SUCCESS("Ders Programı çalışıyor. Ağdaki bilgisayarlar tarayıcıya şu adresi yazsın:"))
        for address in lan_addresses() or ["<bu bilgisayarın IP adresi>"]:
            self.stdout.write(f"    http://{address}:{port}/")
        self.stdout.write(f"Bu bilgisayardan: http://127.0.0.1:{port}/")
        if settings.DEBUG:
            self.stdout.write(self.style.WARNING("Uyarı: DJANGO_DEBUG=1 açık; ağ kurulumunda .env dosyasında DJANGO_DEBUG=0 olmalı."))
        self.stdout.write("Kapatmak için bu pencerede Ctrl+C'ye basın ya da pencereyi kapatın.")
        serve(application, host=options["host"], port=port, threads=options["threads"], ident="DersProgrami")
