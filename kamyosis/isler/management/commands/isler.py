"""Claude'un iş listesiyle çalıştığı komut.

    python manage.py isler liste            # ele alınacak işler (JSON): bekleyen, onaylanmış, yapılmakta kalan
    python manage.py isler goster 12        # bir iş ve notları (JSON)
    python manage.py isler not 12 --durum yapiliyor --metin "Başladım: ..."

Durumlar: bekliyor, yapiliyor, onay (onay bekliyor), soru (soru var), tamam, iptal.
Kural: riskli işlerde (canlıya alma, ortak depoya gönderme, veri silme, parola / yetki / güvenlik ayarı değişikliği,
dışarıya ileti) önce "onay" durumuna alınır ve ne yapılacağı nota yazılır; onaylanmamış riskli iş yapılmaz.
"""

import json
import sys

from django.core.management.base import BaseCommand, CommandError

from isler import servis
from isler.models import Is


def _is(i, notlar=True):
    d = {"id": i.pk, "baslik": i.baslik, "aciklama": i.aciklama, "oncelik": i.oncelik, "durum": i.durum,
         "onaylandi": i.onaylandi, "internetten_girildi": i.dis_erisim,
         "olusturan": i.olusturan.username if i.olusturan else None, "olusturma": i.olusturma.isoformat()}
    if notlar:
        d["notlar"] = [{"claude": n.claude, "yazan": n.yazan.username if n.yazan else None, "durum": n.durum,
                        "metin": n.metin, "zaman": n.zaman.isoformat()} for n in i.notlar.select_related("yazan")]
    return d


class Command(BaseCommand):
    help = "İş listesi: Claude'un okuma ve not yazma arayüzü."

    def add_arguments(self, parser):
        alt = parser.add_subparsers(dest="komut", required=True)
        alt.add_parser("liste")
        g = alt.add_parser("goster")
        g.add_argument("id", type=int)
        n = alt.add_parser("not")
        n.add_argument("id", type=int)
        n.add_argument("--durum", choices=[d for d, _ in Is.DURUMLAR])
        n.add_argument("--metin", default="")

    def _yaz(self, veri):
        sys.stdout.buffer.write((json.dumps(veri, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))

    def handle(self, *args, **o):
        if o["komut"] == "liste":
            from django.db.models import Q

            qs = Is.objects.filter(Q(durum__in=(Is.BEKLIYOR, Is.YAPILIYOR)) | Q(durum=Is.ONAY, onaylandi=True))
            self._yaz({"ele_alinacak": [_is(i) for i in qs.order_by("olusturma")],
                       "bekleyen_onay": Is.objects.filter(durum=Is.ONAY, onaylandi=False).count(),
                       "cevap_bekleyen_soru": Is.objects.filter(durum=Is.SORU).count()})
            return
        i = Is.objects.filter(pk=o["id"]).first()
        if i is None:
            raise CommandError(f"#{o['id']} yok.")
        if o["komut"] == "goster":
            self._yaz(_is(i))
            return
        if not o["durum"] and not o["metin"]:
            raise CommandError("--durum ya da --metin verin.")
        servis.durum_degistir(i, o["durum"] or i.durum, o["metin"], claude=True)
        self._yaz(_is(i, notlar=False))
