from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        from django.db.backends.signals import connection_created

        from .arama import baglanti_kuruldu

        # Türkçe harf duyarsız arama işlevi (tr_sade) her veritabanı bağlantısına eklenir
        connection_created.connect(baglanti_kuruldu, dispatch_uid="core_tr_sade")
