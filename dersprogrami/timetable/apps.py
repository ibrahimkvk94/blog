from django.apps import AppConfig


class TimetableConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "timetable"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in, user_login_failed

        from .access import _on_login, _on_login_failed

        user_logged_in.connect(_on_login, dispatch_uid="timetable_login_audit")
        user_login_failed.connect(_on_login_failed, dispatch_uid="timetable_login_failed_audit")

        from .problem_cache import connect_signals

        connect_signals()  # veri değişince çözücü problemi önbelleği boşalır

        from . import modules
        from .templatetags.navigation import NAV_GROUPS

        # Ders Planlama: bu uygulamanın kendisi. Okul URL'lerinin yetki tabloları access.py'dedir.
        modules.register(modules.Module(
            key="ders", title="Ders Planlama",
            description="Haftalık ders programı: veri girişi, otomatik üretim, düzenleme, vekâlet, nöbet, telafi ve raporlar.",
            icon="grid", namespace="timetable", landing="timetable:school_list", entry="timetable:school_detail",
            nav_groups=NAV_GROUPS, order=10,
        ))
