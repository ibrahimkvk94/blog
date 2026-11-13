from django.apps import AppConfig

# Modül menüsünden kaldırılan öğeler (KAMYOSİS'te kapalı ya da KAMYOSİS'in kendi modülü var)
GIZLI_MENU = {"Vekâlet", "Nöbet çizelgesi", "Öğretmen hesapları", "Kullanıcılar"}


class DersprogramiKopruConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dersprogrami_kopru"
    verbose_name = "Ders Programı köprüsü"

    def ready(self):
        from timetable.templatetags import navigation

        for i, (anahtar, baslik, ogeler) in enumerate(navigation.NAV_GROUPS):
            navigation.NAV_GROUPS[i] = (anahtar, baslik, [o for o in ogeler if o[0] not in GIZLI_MENU])

        # Yalnızca sınav yetkisi olan (Program Hazırlama'yı görmeyen) kullanıcıya menüde yalnızca Sınav Planlama
        # sayfaları; "Ortak veri" (sınıf, öğretmen, ders ...) Ders Planlama sayfalarıdır, gizlenir.
        asil_build = navigation.build

        def build(context):
            from django.urls import reverse

            gruplar = asil_build(context)
            request = context.get("request")
            if request is not None and getattr(request, "sadece_sinav", False):
                onek = reverse("sinav:home")
                gruplar = [{**g, "items": s} for g in gruplar if (s := [o for o in g["items"] if o["url"].startswith(onek)])]
            return gruplar

        navigation.build = build

        from . import sinyaller

        sinyaller.bagla()
