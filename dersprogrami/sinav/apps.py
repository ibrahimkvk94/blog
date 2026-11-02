from django.apps import AppConfig


class SinavConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sinav"
    verbose_name = "Sınav Planlama"

    def ready(self):
        from timetable import modules

        from .module import MODULE

        modules.register(MODULE)
