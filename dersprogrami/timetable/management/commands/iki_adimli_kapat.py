"""Telefonu ve kurtarma kodları elinde olmayan kullanıcının (çoğunlukla merkez yöneticinin) iki adımlı girişini
sunucu bilgisayarından kaldırır: python manage.py iki_adimli_kapat <kullanıcı adı>"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from timetable import two_factor


class Command(BaseCommand):
    help = "Kullanıcının iki adımlı girişini kaldırır (girişte yalnızca parola sorulur)."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, username, **options):
        User = get_user_model()
        user = User.objects.filter(**{User.USERNAME_FIELD: username}).first()
        if user is None:
            raise CommandError(f"{username} adlı kullanıcı yok.")
        if not two_factor.is_enabled(user) and not two_factor.setup_record(user):
            self.stdout.write(f"{username} için iki adımlı giriş zaten kapalı.")
            return
        two_factor.disable(user)
        self.stdout.write(self.style.SUCCESS(f"{username} için iki adımlı giriş kaldırıldı."))
